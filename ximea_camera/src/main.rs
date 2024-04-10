// External crate imports
use clap::Parser;
use crossbeam::channel;
use image::{ImageBuffer, Luma};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

// Local module declarations
mod frames;
mod helpers;
mod structs;

// Imports from local modules
use crate::frames::frame_handler;
use helpers::*;
use structs::*;

fn main() -> Result<(), i32> {
    // set logging level
    if std::env::var_os("RUST_LOG").is_none() {
        std::env::set_var("RUST_LOG", "info");
    }

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

    // calculate frames before and after
    let n_before = (args.t_before * args.fps) as usize;
    let n_after = (args.t_after * args.fps) as usize;
    log::debug!(
        "Recording {} frames before and {} after trigger",
        n_before,
        n_after
    );

    // Connect to ZMQ; return error if connection fails
    log::info!("Connecting to ZMQ server at {}", args.address);
    let socket = connect_to_zmq(&args.address).unwrap();

    // Wait for ready message from socket
    log::info!("Waiting for ready message from ZMQ PUB");
    let mut msg = zmq::Message::new();

    // Block until first message, which should be the save folder
    socket.recv(&mut msg, 0).unwrap();
    let mut save_folder: String = String::new();

    match parse_message(msg.as_str().unwrap()) {
        MessageType::JsonData(data) => {
            log::error!("Expected text message, got JSON data: {:?}", data);
        }
        MessageType::Text(data) => {
            save_folder = data;
            log::info!("Got save folder: {}", &save_folder);
        }
        MessageType::Empty => {
            //log::error!("Empty message received");
        }
    }

    // spawn writer thread
    let (sender, receiver) = channel::unbounded::<(Arc<ImageData>, MessageType)>();
    let frame_handler =
        std::thread::spawn(move || frame_handler(receiver, n_before, n_after, save_folder));

    // create image buffer
    let buffer = cam.start_acquisition()?;
    let mut image_data: Arc<ImageData> = Arc::new(ImageData::default());

    // start acquisition
    log::info!("Starting acquisition");
    while running.load(Ordering::SeqCst) {
        // receive message
        match socket.recv(&mut msg, zmq::DONTWAIT) {
            Ok(_) => log::info!("Received message: {}", msg.as_str().unwrap()),
            Err(_) => {
                // do nothing
            }
        }
        let parsed_message = parse_message(msg.as_str().unwrap());

        // check if got "kill" in parsed_message
        match &parsed_message {
            MessageType::Text(data) => {
                if data == "kill" {
                    break;
                }
            }
            _ => {}
        }

        // Get frame from camera
        let frame = buffer.next_image::<u8>(None)?;

        // Put frame data to struct
        image_data = Arc::new(ImageData {
            width: frame.width(),
            height: frame.height(),
            nframe: frame.nframe(),
            acq_nframe: frame.acq_nframe(),
            timestamp_raw: frame.timestamp_raw(),
            exposure_time: frame.exposure_time_us(),
            data: ImageBuffer::<Luma<u8>, Vec<u8>>::from(frame),
        });

        // send frame with the incoming parsed message
        match sender.send((image_data, parsed_message)) {
            Ok(_) => {}
            Err(_e) => {} //log::error!("Failed to send frame: {}", e),
        }
    }

    // stop acquisition
    buffer.stop_acquisition()?;

    // send kill signal
    match sender.send((
        Arc::new(ImageData::default()),
        MessageType::Text("kill".to_string()),
    )) {
        Ok(_) => {
            log::info!("Sent kill message to frame handler");
        }
        Err(_e) => {
            log::error!("Failed to send kill trigger to frame handler.")
        }
    }

    // stop frame handler
    frame_handler.join().unwrap();

    Ok(())
}
