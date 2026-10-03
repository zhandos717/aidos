use std::collections::VecDeque;
use std::path::Path;

use ort::session::Session;
use ort::value::Tensor;

use crate::audio::i16_to_f32;

pub const FRAME: usize = 512;
const CONTEXT: usize = 64;
const RATE: i64 = 16000;

pub trait SpeechProb: Send {
    fn prob(&mut self, frame: &[f32]) -> f32;
    fn reset(&mut self);
}

#[derive(Clone, Copy, Debug)]
pub struct SegmenterParams {
    pub threshold: f32,
    pub frame_ms: u32,
    pub min_speech_ms: u32,
    pub end_silence_ms: u32,
    pub max_utterance_ms: u32,
    pub pre_roll_ms: u32,
}

impl Default for SegmenterParams {
    fn default() -> Self {
        Self { threshold: 0.5, frame_ms: 32, min_speech_ms: 250, end_silence_ms: 1000, max_utterance_ms: 12000, pre_roll_ms: 300 }
    }
}

pub struct Segmenter {
    p: SegmenterParams,
    max_frames: usize,
    pre_roll: VecDeque<Vec<i16>>,
    pre_roll_cap: usize,
    frames: Vec<Vec<i16>>,
    speech_ms: u32,
    silence_ms: u32,
}

impl Segmenter {
    pub fn new(p: SegmenterParams) -> Self {
        let pre_roll_cap = ((p.pre_roll_ms / p.frame_ms) as usize).max(1);
        Self {
            max_frames: (p.max_utterance_ms / p.frame_ms) as usize,
            pre_roll: VecDeque::with_capacity(pre_roll_cap),
            pre_roll_cap,
            frames: Vec::new(),
            speech_ms: 0,
            silence_ms: 0,
            p,
        }
    }

    pub fn triggered(&self) -> bool {
        !self.frames.is_empty()
    }

    pub fn reset(&mut self) {
        self.frames.clear();
        self.pre_roll.clear();
        self.speech_ms = 0;
        self.silence_ms = 0;
    }

    pub fn feed(&mut self, frame: &[i16], prob: f32) -> Option<Vec<i16>> {
        let is_speech = prob >= self.p.threshold;

        if self.frames.is_empty() {
            if !is_speech {
                if self.pre_roll.len() == self.pre_roll_cap {
                    self.pre_roll.pop_front();
                }
                self.pre_roll.push_back(frame.to_vec());
                return None;
            }
            self.frames.extend(self.pre_roll.drain(..));
            self.frames.push(frame.to_vec());
            self.speech_ms = self.p.frame_ms;
            return None;
        }

        self.frames.push(frame.to_vec());
        if is_speech {
            self.speech_ms += self.p.frame_ms;
            self.silence_ms = 0;
        } else {
            self.silence_ms += self.p.frame_ms;
        }

        let too_long = self.frames.len() >= self.max_frames;
        if self.silence_ms < self.p.end_silence_ms && !too_long {
            return None;
        }
        let utterance = (self.speech_ms >= self.p.min_speech_ms).then(|| self.frames.concat());
        self.reset();
        utterance
    }
}

pub struct Endpointer<P: SpeechProb> {
    prob: P,
    seg: Segmenter,
    pending: Vec<i16>,
}

impl<P: SpeechProb> Endpointer<P> {
    pub fn new(prob: P, p: SegmenterParams) -> Self {
        Self { prob, seg: Segmenter::new(p), pending: Vec::new() }
    }

    pub fn push(&mut self, pcm: &[i16]) -> Vec<Vec<i16>> {
        self.pending.extend_from_slice(pcm);
        let mut out = Vec::new();
        let full = self.pending.len() / FRAME * FRAME;
        for frame in self.pending[..full].chunks_exact(FRAME) {
            let prob = self.prob.prob(&i16_to_f32(frame));
            if let Some(utterance) = self.seg.feed(frame, prob) {
                out.push(utterance);
            }
        }
        self.pending.drain(..full);
        out
    }

    pub fn reset(&mut self) {
        self.seg.reset();
        self.pending.clear();
        self.prob.reset();
    }
}

pub struct SileroVad {
    session: Session,
    state: Vec<f32>,
    context: Vec<f32>,
}

impl SileroVad {
    pub fn load(path: &Path) -> anyhow::Result<Self> {
        let session = Session::builder()?.commit_from_file(path)?;
        Ok(Self { session, state: vec![0.0; 2 * 128], context: vec![0.0; CONTEXT] })
    }

    fn infer(&mut self, frame: &[f32]) -> anyhow::Result<f32> {
        let mut input = Vec::with_capacity(CONTEXT + FRAME);
        input.extend_from_slice(&self.context);
        input.extend_from_slice(frame);
        let outputs = self.session.run(ort::inputs![
            "input" => Tensor::from_array(([1usize, CONTEXT + FRAME], input.clone()))?,
            "state" => Tensor::from_array(([2usize, 1, 128], self.state.clone()))?,
            "sr" => Tensor::from_array(((), vec![RATE]))?,
        ])?;
        let (_, prob) = outputs["output"].try_extract_tensor::<f32>()?;
        let (_, state) = outputs["stateN"].try_extract_tensor::<f32>()?;
        let prob = prob[0];
        self.state.copy_from_slice(state);
        self.context.copy_from_slice(&input[input.len() - CONTEXT..]);
        Ok(prob)
    }
}

impl SpeechProb for SileroVad {
    fn prob(&mut self, frame: &[f32]) -> f32 {
        self.infer(frame).unwrap_or_else(|err| {
            tracing::warn!(%err, "silero inference failed");
            0.0
        })
    }

    fn reset(&mut self) {
        self.state.fill(0.0);
        self.context.fill(0.0);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const FMS: u32 = 32;

    fn ms(v: u32) -> usize {
        v.div_ceil(FMS) as usize
    }

    fn feed(seg: &mut Segmenter, probs: &[f32]) -> Vec<Vec<i16>> {
        probs.iter().enumerate().filter_map(|(i, &p)| seg.feed(&vec![i as i16; FRAME], p)).collect()
    }

    fn params(f: impl FnOnce(&mut SegmenterParams)) -> SegmenterParams {
        let mut p = SegmenterParams::default();
        f(&mut p);
        p
    }

    fn probs(parts: &[(f32, usize)]) -> Vec<f32> {
        parts.iter().flat_map(|&(p, n)| std::iter::repeat_n(p, n)).collect()
    }

    #[test]
    fn silence_yields_nothing() {
        let mut seg = Segmenter::new(SegmenterParams::default());
        assert!(feed(&mut seg, &probs(&[(0.0, ms(5000))])).is_empty());
        assert!(!seg.triggered());
    }

    #[test]
    fn utterance_ends_after_silence() {
        let mut seg = Segmenter::new(params(|p| p.pre_roll_ms = 96));
        let out = feed(&mut seg, &probs(&[(0.0, 10), (0.9, ms(800)), (0.1, ms(1000))]));
        assert_eq!(out.len(), 1);
        assert_eq!(out[0].len(), (ms(96) + ms(800) + ms(1000)) * FRAME);
        assert!(!seg.triggered());
    }

    #[test]
    fn short_noise_is_dropped() {
        let mut seg = Segmenter::new(SegmenterParams::default());
        assert!(feed(&mut seg, &probs(&[(0.9, ms(100)), (0.0, ms(1000))])).is_empty());
    }

    #[test]
    fn short_pause_does_not_split() {
        let mut seg = Segmenter::new(SegmenterParams::default());
        let out = feed(&mut seg, &probs(&[(0.9, ms(500)), (0.0, ms(500)), (0.9, ms(500)), (0.0, ms(1000))]));
        assert_eq!(out.len(), 1);
    }

    #[test]
    fn max_length_cuts_utterance() {
        let mut seg = Segmenter::new(params(|p| p.max_utterance_ms = 2000));
        let out = feed(&mut seg, &probs(&[(0.9, ms(5000))]));
        assert_eq!(out.len(), 2);
        assert!(out.iter().all(|u| u.len() == (2000 / FMS) as usize * FRAME));
    }

    struct Loud;
    impl SpeechProb for Loud {
        fn prob(&mut self, frame: &[f32]) -> f32 {
            if frame.iter().any(|s| s.abs() > 0.01) { 1.0 } else { 0.0 }
        }
        fn reset(&mut self) {}
    }

    #[test]
    fn endpointer_reframes_arbitrary_chunks() {
        let mut ep = Endpointer::new(Loud, SegmenterParams::default());
        let mut pcm = vec![1000i16; 16000];
        pcm.extend(vec![0i16; 24000]);
        let mut out = Vec::new();
        for chunk in pcm.chunks(960) {
            out.extend(ep.push(chunk));
        }
        assert_eq!(out.len(), 1);
        assert!(out[0].len() >= 16000);
    }

    #[test]
    fn silero_detects_speech_in_fixture() {
        let manifest = env!("CARGO_MANIFEST_DIR");
        let mut vad = SileroVad::load(&Path::new(manifest).join("models/silero_vad.onnx")).unwrap();
        let mut reader = hound::WavReader::open(Path::new(manifest).join("tests/fixtures/speech_16k.wav")).unwrap();
        let pcm: Vec<i16> = reader.samples::<i16>().map(Result::unwrap).collect();
        let speech = pcm.chunks_exact(FRAME).filter(|f| vad.prob(&i16_to_f32(f)) > 0.5).count();
        assert!(speech * 2 > pcm.len() / FRAME, "speech frames: {speech}");
        vad.reset();
        assert!(vad.prob(&vec![0.0; FRAME]) < 0.5);
    }
}
