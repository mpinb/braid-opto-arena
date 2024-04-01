use clap::{Error, Parser};
use ctrlc;
use log;
use std::collections::VecDeque;
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc,
};
use std::time::{Duration, Instant};
use zmq::Context;

#[derive(Parser, Debug)]
#[command(version, about, long_about = None)]
struct Args {
    #[arg(long, default_value = "1000")]
    exposure: f32,

    #[arg(long, default_value = "200")]
    fps: f32,

    #[arg(long, default_value = "10")]
    runtime: u32,

    #[arg(long, default_value = "2496")]
    width: u32,

    #[arg(long, default_value = "2496")]
    height: u32,
}

// fn setup_zme()
fn setup_camera(cam: &mut xiapi::Camera, args: &Args) -> Result<(), xiapi::XI_RETURN> {
    cam.set_exposure(args.exposure)?;
    cam.set_image_data_format(xiapi::XI_IMG_FORMAT::XI_MONO8)?;
    cam.set_acq_timing_mode(xiapi::XI_ACQ_TIMING_MODE::XI_ACQ_TIMING_MODE_FRAME_RATE_LIMIT)?;
    cam.set_framerate(args.fps)?;
    cam.set_height(args.height)?;
    cam.set_width(args.width)?;

    cam.set_limit_bandwidth(cam.limit_bandwidth_maximum()?)?;
    let buffer_size = cam.acq_buffer_size()?;
    cam.set_acq_buffer_size(buffer_size * 4)?;
    cam.set_buffers_queue_size(cam.buffers_queue_size_maximum()?)?;

    Ok(())
}
fn main() -> Result<(), i32> {
    env_logger::init();

    // Create a boolean flag to indicate if Ctrl+C has been pressed
    let running = Arc::new(AtomicBool::new(true));
    let r = running.clone();

    // Register a handler for Ctrl+C signals
    ctrlc::set_handler(move || {
        r.store(false, Ordering::SeqCst);
    })
    .expect("Error setting Ctrl-C handler");

    // Create a ZMQ context and socket
    let context = Context::new();
    let subscriber = context.socket(zmq::SUB).unwrap();

    assert!(subscriber.connect("tcp://localhost:5555").is_ok());
    assert!(subscriber.set_subscribe(b"").is_ok()); // Subscribe to all messages

    // Argument parser
    let args: Args = Args::parse();

    // Create a deque to store images
    let mut pre_buffer: VecDeque<Vec<u8>> = VecDeque::with_capacity(args.fps as usize);
    let mut post_buffer: VecDeque<Vec<u8>> = VecDeque::with_capacity(args.fps as usize * 2);
    let mut switch = false;
    let mut iteration_times: Vec<Duration> = Vec::new();

    // Open the camera
    let mut cam = xiapi::open_device(None)?;

    // Set camera parameters
    setup_camera(&mut cam, &args)?;

    // Start acquisition
    let buffer = cam.start_acquisition()?;
    log::info!("Acquisition started");

    while running.load(Ordering::SeqCst) {
        // Start time
        let start_time = Instant::now();

        // Attempt to receive a message from the socket

        if let Ok(msg) = subscriber.recv_msg(zmq::DONTWAIT) {
            if msg.as_str().unwrap() == "start" {
                log::info!("Received start message");
                switch = true;
            } else if msg.as_str().unwrap() == "stop" {
                log::info!("Received stop message");
                break;
            } else {
                log::info!("Unknown message: {}", msg.as_str().unwrap());
            }
        } else {
            // No message available yet, do something else or sleep
        }
        // Get the next image from the camera
        let image = buffer.next_image::<u8>(None)?.data().to_vec();

        // Push the image to the appropriate buffer
        if !switch {
            if pre_buffer.len() == pre_buffer.capacity() {
                pre_buffer.pop_front();
            }
            pre_buffer.push_back(image);
        } else if switch && post_buffer.len() < post_buffer.capacity() {
            post_buffer.push_back(image);
        } else {
            log::debug!("Buffers full");
            log::debug!("len(pre_buffer): {}", pre_buffer.len());
            log::debug!("len(post_buffer): {}", post_buffer.len());

            let mut pre_buffer_clone = pre_buffer.clone();
            let mut post_buffer_clone = post_buffer.clone();
            pre_buffer_clone.append(&mut post_buffer_clone);

            //
            pre_buffer.clear();
            assert!(pre_buffer.is_empty());
            log::debug!("length of pre_buffer: {}", pre_buffer.len());

            post_buffer.clear();
            assert!(post_buffer.is_empty());
            log::debug!("length of post_buffer: {}", post_buffer.len());

            switch = false;
        }

        // end time
        let end_time = Instant::now();
        let elapsed_time = end_time.duration_since(start_time);
        iteration_times.push(elapsed_time);
    }

    // print iteration time
    log::info!(
        "Average iteration time: {:?}",
        iteration_times.iter().sum::<Duration>() / iteration_times.len() as u32
    );

    // print average fps
    log::info!(
        "Average FPS: {:?}",
        1.0 / (iteration_times.iter().sum::<Duration>().as_secs_f64()
            / iteration_times.len() as f64)
    );

    Ok(())
}
