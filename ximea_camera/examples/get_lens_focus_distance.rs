use xiapi;

fn main() -> Result<(), i32> {
    let mut cam = xiapi::open_device(None)?;
    let buffer = cam.start_acquisition()?;

    unsafe { xiapi::xiGetParamFloat(*cam, xiapi_sys::XI_PRM_LENS_FOCUS_DISTANCE, val) }

    Ok(())
}
