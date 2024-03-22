/*
 * Copyright (c) 2022. XIMEA GmbH - All Rights Reserved
 */
//use xiapi_sys::XI_IMG_FORMAT;

use std::collections::VecDeque;
use std::time::{Duration, Instant};
use xiapi::{xiSetParamFloat, Image, XI_IMG_FORMAT, XI_PRM_EXPOSURE};

fn main() -> Result<(), i32> {
    let mut deque: VecDeque<Image<'_, u8>> = VecDeque::with_capacity(1000);

    let mut iteration_times: Vec<Duration> = Vec::new();
    let mut cam = xiapi::open_device(None)?;

    let fps = 400; // frames per second
    let runtime = 10; // seconds
    let width = 2496;
    let height = 2496;
    println!(
        "Starting acquisition for {} seconds at {} fps",
        runtime, fps
    );

    unsafe {
        xiSetParamFloat(
            *cam,
            XI_PRM_EXPOSURE.as_ptr() as *const ::std::os::raw::c_char,
            5000.0,
        );
    }

    // Set camera parameters
    cam.set_exposure(1000.0)?;
    cam.set_image_data_format(XI_IMG_FORMAT::XI_MONO8)?;
    cam.set_acq_timing_mode(xiapi::XI_ACQ_TIMING_MODE::XI_ACQ_TIMING_MODE_FRAME_RATE_LIMIT)?;
    cam.set_framerate(fps as f32)?;
    // cam.set_acq_timing_mode(xiapi::XI_ACQ_TIMING_MODE::XI_ACQ_TIMING_MODE_FREE_RUN)?;
    cam.set_height(height)?;
    cam.set_width(width)?;

    // Set camera bandwidth
    cam.set_limit_bandwidth(cam.limit_bandwidth_maximum()?)?;
    let buffer_size = cam.acq_buffer_size()?;
    cam.set_acq_buffer_size(buffer_size * 4)?;
    cam.set_buffers_queue_size(cam.buffers_queue_size_maximum()?)?;

    // Start acquisition
    let buffer = cam.start_acquisition()?;

    let iterations = fps * runtime;
    for _i in 0..iterations {
        let start_time = Instant::now();
        let image = buffer.next_image::<u8>(None)?;

        deque.push_back(image);

        let end_time = Instant::now();

        let duration = end_time - start_time;
        iteration_times.push(duration);
    }

    // Calculate average time
    let total_duration: Duration = iteration_times.iter().sum();
    let average_duration = total_duration / iterations as u32;

    // Print average time
    println!("Total time: {:?}", total_duration);
    println!("Average time per iteration: {:?}", average_duration);
    println!("FPS = {:?}", 1.0 / average_duration.as_secs_f64());

    Ok(())
}
