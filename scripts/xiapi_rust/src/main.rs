use clap::Parser;
use std::collections::VecDeque;
use std::time::{Duration, Instant};
use xiapi;

use ctrlc;
use zmq;

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

#[derive(Parser, Debug)]
#[command(version, about, long_about = None)]
struct Args {
    #[arg(long, default_value = "1000")]
    exposure: f32,

    #[arg(long, default_value = "400")]
    fps: f32,

    #[arg(long, default_value = "10")]
    runtime: u32,

    #[arg(long, default_value = "2496")]
    width: u32,

    #[arg(long, default_value = "2048")]
    height: u32,
}

fn main() -> Result<(), i32> {
    // Create a boolean flag to indicate if Ctrl+C has been pressed
    let running = Arc::new(AtomicBool::new(true));
    let r = running.clone();

    // Register a handler for Ctrl+C signals
    ctrlc::set_handler(move || {
        r.store(false, Ordering::SeqCst);
    })
    .expect("Error setting Ctrl-C handler");

    // Create a ZMQ context and socket
    let ctx = zmq::Context::new();
    let socket = ctx.socket(zmq::STREAM).unwrap();
    socket.bind("tcp://*:5555").unwrap();
    let mut msg = zmq::Message::new();

    // Argument parser
    let args = Args::parse();

    // Create a deque to store images
    let mut pre_buffer: VecDeque<xiapi::Image<'_, u8>> = VecDeque::with_capacity(args.fps as usize);
    let mut post_buffer: VecDeque<xiapi::Image<'_, u8>> =
        VecDeque::with_capacity(args.fps as usize * 2);
    let mut switch = false;
    let mut iteration_times: Vec<Duration> = Vec::new();

    // Open the camera
    let mut cam = xiapi::open_device(None)?;

    // Set camera parameters
    cam.set_exposure(args.exposure)?;
    cam.set_image_data_format(xiapi::XI_IMG_FORMAT::XI_MONO8)?;
    cam.set_acq_timing_mode(xiapi::XI_ACQ_TIMING_MODE::XI_ACQ_TIMING_MODE_FRAME_RATE_LIMIT)?;
    cam.set_framerate(args.fps)?;
    cam.set_height(args.height)?;
    cam.set_width(args.width)?;

    // Set camera bandwidth
    cam.set_limit_bandwidth(cam.limit_bandwidth_maximum()?)?;
    let buffer_size = cam.acq_buffer_size()?;
    cam.set_acq_buffer_size(buffer_size * 4)?;
    cam.set_buffers_queue_size(cam.buffers_queue_size_maximum()?)?;

    // Start acquisition
    let buffer = cam.start_acquisition()?;
    println!("Acquisition started");

    while running.load(Ordering::SeqCst) {
        // Start time
        let start_time = Instant::now();

        // Attempt to receive a message from the socket
        match socket.recv(&mut msg, zmq::DONTWAIT) {
            Ok(_) => {
                if msg.as_str().unwrap() == "stop" {
                    break;
                } else if msg.as_str().unwrap() == "start" {
                    switch = true;
                } else {
                    // pass
                }
            }
            Err(_) => {
                // do nothing
            }
        }

        // Get the next image from the camera
        let image = buffer.next_image::<u8>(None)?;

        // Add frames to the appropriate buffer
        if !switch {
            pre_buffer.push_back(image);
        } else if post_buffer.len() < post_buffer.capacity() {
            post_buffer.push_back(image);
        } else {
            println!("Second buffer is full");

            // clear both buffers
            pre_buffer.clear();
            post_buffer.clear();
            switch = false;
        }

        // end time
        let end_time = Instant::now();
        let elapsed_time = end_time.duration_since(start_time);
        iteration_times.push(elapsed_time);
    }

    // print iteration time
    println!(
        "Average iteration time: {:?}",
        iteration_times.iter().sum::<Duration>() / iteration_times.len() as u32
    );

    // print average fps
    println!(
        "Average FPS: {:?}",
        1.0 / (iteration_times.iter().sum::<Duration>().as_secs_f64()
            / iteration_times.len() as f64)
    );

    Ok(())
}
