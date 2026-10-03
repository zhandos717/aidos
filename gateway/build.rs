fn main() -> Result<(), Box<dyn std::error::Error>> {
    // SAFETY: build scripts are single-threaded.
    unsafe { std::env::set_var("PROTOC", protoc_bin_vendored::protoc_bin_path()?) };
    println!("cargo:rerun-if-changed=../proto/link.proto");
    tonic_prost_build::configure().compile_protos(&["../proto/link.proto"], &["../proto"])?;
    Ok(())
}
