pub const UP_RATE: u32 = 16000;
pub const DOWN_RATE: u32 = 24000;
pub const DOWN_FRAME: usize = (DOWN_RATE as usize) * 60 / 1000;
const MAX_DECODED: usize = 5760;

pub struct UpDecoder(opus::Decoder);

impl UpDecoder {
    pub fn new() -> anyhow::Result<Self> {
        Ok(Self(opus::Decoder::new(UP_RATE, opus::Channels::Mono)?))
    }

    pub fn decode(&mut self, packet: &[u8]) -> anyhow::Result<Vec<i16>> {
        let mut out = vec![0i16; MAX_DECODED];
        let n = self.0.decode(packet, &mut out, false)?;
        out.truncate(n);
        Ok(out)
    }
}

pub struct DownEncoder(opus::Encoder);

impl DownEncoder {
    pub fn new() -> anyhow::Result<Self> {
        Ok(Self(opus::Encoder::new(DOWN_RATE, opus::Channels::Mono, opus::Application::Voip)?))
    }

    pub fn encode_all(&mut self, pcm: &[i16]) -> anyhow::Result<Vec<Vec<u8>>> {
        let mut packets = Vec::with_capacity(pcm.len().div_ceil(DOWN_FRAME));
        let mut frame = vec![0i16; DOWN_FRAME];
        let mut buf = vec![0u8; 4000];
        for chunk in pcm.chunks(DOWN_FRAME) {
            frame[..chunk.len()].copy_from_slice(chunk);
            frame[chunk.len()..].fill(0);
            let len = self.0.encode(&frame, &mut buf)?;
            packets.push(buf[..len].to_vec());
        }
        Ok(packets)
    }
}

pub fn resample(pcm: &[i16], from: u32, to: u32) -> Vec<i16> {
    if from == to || pcm.is_empty() {
        return pcm.to_vec();
    }
    let out_len = (pcm.len() as u64 * to as u64 / from as u64) as usize;
    let step = from as f64 / to as f64;
    (0..out_len)
        .map(|i| {
            let pos = i as f64 * step;
            let idx = pos as usize;
            let frac = pos - idx as f64;
            let a = pcm[idx.min(pcm.len() - 1)] as f64;
            let b = pcm[(idx + 1).min(pcm.len() - 1)] as f64;
            (a + (b - a) * frac).round() as i16
        })
        .collect()
}

pub fn pcm_from_le_bytes(bytes: &[u8]) -> Vec<i16> {
    bytes.chunks_exact(2).map(|b| i16::from_le_bytes([b[0], b[1]])).collect()
}

pub fn pcm_to_le_bytes(pcm: &[i16]) -> Vec<u8> {
    pcm.iter().flat_map(|s| s.to_le_bytes()).collect()
}

pub fn i16_to_f32(pcm: &[i16]) -> Vec<f32> {
    pcm.iter().map(|&s| s as f32 / 32768.0).collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sine(rate: u32, ms: u32) -> Vec<i16> {
        let n = (rate * ms / 1000) as usize;
        (0..n)
            .map(|i| ((i as f32 * 440.0 * std::f32::consts::TAU / rate as f32).sin() * 8000.0) as i16)
            .collect()
    }

    #[test]
    fn up_roundtrip_60ms() {
        let mut enc = opus::Encoder::new(UP_RATE, opus::Channels::Mono, opus::Application::Voip).unwrap();
        let mut packet = vec![0u8; 4000];
        let len = enc.encode(&sine(UP_RATE, 60), &mut packet).unwrap();
        let pcm = UpDecoder::new().unwrap().decode(&packet[..len]).unwrap();
        assert_eq!(pcm.len(), 960);
    }

    #[test]
    fn encode_all_pads_last_frame() {
        let frames = DownEncoder::new().unwrap().encode_all(&sine(DOWN_RATE, 130)).unwrap();
        assert_eq!(frames.len(), 3);
        assert!(frames.iter().all(|f| !f.is_empty()));
    }

    #[test]
    fn resample_lengths() {
        assert_eq!(resample(&sine(22050, 1000), 22050, 24000).len(), 24000);
        assert_eq!(resample(&sine(16000, 500), 16000, 24000).len(), 12000);
        assert_eq!(resample(&[1, 2, 3], 24000, 24000), vec![1, 2, 3]);
        assert!(resample(&[], 16000, 24000).is_empty());
    }

    #[test]
    fn le_bytes_roundtrip() {
        let pcm = vec![0i16, -1, 1000, i16::MIN, i16::MAX];
        assert_eq!(pcm_from_le_bytes(&pcm_to_le_bytes(&pcm)), pcm);
    }
}
