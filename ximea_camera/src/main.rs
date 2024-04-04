use clap::Parser;
use crossbeam::channel;
use image::{ImageBuffer, Luma};
use log;
use std::collections::VecDeque;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use xiapi;

mod structs;
use structs::*;

mod helpers;
use helpers::*;

mod image_processor;
use image_processor::process_packets;

fn main() -> Result<(), i32> {
    // setup logger
    env_logger::init();

    // setup ctrl-c handler
    let running = Arc::new(AtomicBool::new(true));
    setup_ctrlc_handler(running.clone());

    // Parse command line arguments
    let args = Args::parse();

    // Open the camera
    let mut cam = xiapi::open_device(Some(0))?;

    // Set camera parameters
    set_camera_parameters(&mut cam, &args)?;

    // setup buffers
    let mut pre_buffer: VecDeque<Arc<ImageData>> =
        VecDeque::with_capacity(args.t_before as usize * args.fps as usize);
    let mut post_buffer: VecDeque<Arc<ImageData>> =
        VecDeque::with_capacity(args.t_after as usize * args.fps as usize);
    let mut switch = false;

    // Connect to ZMQ; return error if connection fails
    log::info!("Connecting to ZMQ server at {}", args.address);
    let socket = connect_to_zmq(&args.address).unwrap();

    // Wait for ready message from socket
    log::info!("Waiting for ready message from ZMQ PUB");
    let mut msg = zmq::Message::new();
    let save_folder: String;

    // First message should be the save folder
    match socket.recv(&mut msg, 0) {
        Ok(_) => {
            save_folder = msg.as_str().unwrap_or_default().to_string();
            log::info!("Got save folder: {}", &save_folder);
        }
        Err(e) => {
            log::error!("Failed to receive ready message: {}", e);
            return Err(1);
        }
    }

    // spawn writer thread
    let (sender, receiver) = channel::unbounded::<(Packet, KalmanEstimateRow)>();
    let writer_thread = std::thread::spawn(move || process_packets(save_folder, receiver));

    // setup trigger
    let mut trigger: KalmanEstimateRow;

    // create image buffer
    let buffer = cam.start_acquisition()?;
    log::info!("Starting acquisition");
    while running.load(Ordering::SeqCst) {
        // Get msg from zmq
        if let Ok(msg) = socket.recv_msg(zmq::DONTWAIT) {
            trigger = serde_json::from_str(msg.as_str().unwrap()).unwrap();
            switch = true;
        } else {
            trigger = KalmanEstimateRow::default();
        }

        // Get frame from camera
        let frame = buffer.next_image::<u8>(None)?;

        // Put frame data to struct
        let image_data = Arc::new(ImageData {
            width: frame.width(),
            height: frame.height(),
            nframe: frame.nframe(),
            acq_nframe: frame.acq_nframe(),
            timestamp_raw: frame.timestamp_raw(),
            data: ImageBuffer::<Luma<u8>, Vec<u8>>::from(frame),
        });

        // Add frame to appropriate buffer
        if !switch {
            if pre_buffer.len() == pre_buffer.capacity() {
                pre_buffer.pop_front();
            }
            pre_buffer.push_back(image_data);
        } else {
            post_buffer.push_back(image_data);
        };

        // If buffer is full, send to writer thread
        if post_buffer.len() == post_buffer.capacity() && switch {
            println!("Sending buffer to writer thread");
            // get current time
            let start = time();

            // Preallocate the combined buffer to the sum of lengths to avoid reallocations.
            let combined_buffer: Vec<Arc<ImageData>> = pre_buffer
                .iter()
                .chain(post_buffer.iter())
                .cloned()
                .collect();

            // Clear both buffers.
            pre_buffer.clear();
            post_buffer.clear();

            // Send combined_buffer to writer thread.
            match sender.send((Packet::Images(combined_buffer), trigger)) {
                Ok(_) => log::info!("Buffer sent to writer thread."),
                Err(e) => log::error!("Failed to send buffer: {}", e),
            }

            // Reset switch (this line was left unchanged, assuming switch is a variable in your scope).
            switch = false;

            // get end time
            let end = time();

            // print how long this whole block took
            println!("Time taken to process: {}", end - start);
        };
    }

    // stop acquisition
    buffer.stop_acquisition()?;

    // send kill packet
    match sender.send((Packet::Kill, KalmanEstimateRow::default())) {
        Ok(_) => log::info!("Kill signal sent to writer thread."),
        Err(e) => log::error!("Failed to send kill signal: {}", e),
    }

    // join thread
    match writer_thread.join() {
        Ok(_) => log::info!("Writer thread stopped."),
        Err(e) => log::error!("Failed to stop writer thread: {:?}", e),
    }

    Ok(())
}