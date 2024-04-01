//use opencv::prelude::*;
use bounded_vec_deque::BoundedVecDeque;
//use crossbeam::channel;
use chrono;
use chrono::prelude::*;
use image::{ImageBuffer, Luma};
use opencv as cv;
use opencv::prelude::*;
use std::sync::{mpsc, Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};
use xiapi;

struct ImageData {
    data: ImageBuffer<Luma<u8>, Vec<u8>>,
    width: u32,
    height: u32,
    nframe: u32,
    acq_nframe: u32,
    timestamp_raw: u64,
}

fn process_packets(rx: Arc<Mutex<std::sync::mpsc::Receiver<Vec<ImageData>>>>) {
    loop {
        let packet = rx.lock().unwrap().recv().unwrap();

        let current_datetime = Local::now();
        let formatted_datetime = current_datetime.format("%Y-%m-%d-%H-%M-%S");
        let filename = format!("{}.mp4", formatted_datetime);
        let fourcc = cv::videoio::VideoWriter::fourcc('H', '2', '6', '4').unwrap();
        println!("fourcc = {}", fourcc);
        let mut writer = cv::videoio::VideoWriter::new(
            filename.as_str(),
            fourcc,
            30.0,
            cv::core::Size::new(2496, 2496),
            false,
        )
        .unwrap();

        println!("Writing video");
        for image_data in packet.iter() {
            let img = cv::core::Mat::from_slice(image_data.data.as_raw()).unwrap();
            writer.write(&img).unwrap();
        }
        println!("Video written");

        writer.release().unwrap();
        break;
    }
}

fn main() -> Result<(), i32> {
    // open camera
    let mut cam = xiapi::open_device(None)?;

    let fps = 200.0;
    let width = 2496;
    let height = 2496;
    let exposure = 2000.0;

    let (tx, rx) = mpsc::channel();
    let rx = Arc::new(Mutex::new(rx));

    // Spawn a thread to run the process_packets function
    let handle = thread::spawn(move || {
        process_packets(rx);
    });

    cam.set_exposure(exposure)?;
    cam.set_image_data_format(xiapi::XI_IMG_FORMAT::XI_MONO8)?;
    cam.set_acq_timing_mode(xiapi::XI_ACQ_TIMING_MODE::XI_ACQ_TIMING_MODE_FRAME_RATE_LIMIT)?;
    cam.set_framerate(fps)?;

    // let offset_x = (4704 - 2496) / 2;
    // let offest_y = (3424 - 2496) / 2;
    // unsafe {
    //     xiapi::xiSetParamInt(*cam, xiapi::XI_PRM_OFFSET_X.as_ptr() as *const i8, offset_x);
    //     xiapi::xiSetParamInt(*cam, xiapi::XI_PRM_OFFSET_Y.as_ptr() as *const i8, offest_y);
    // }
    cam.set_height(height)?;
    cam.set_width(width)?;

    cam.set_limit_bandwidth(cam.limit_bandwidth_maximum()?)?;
    let buffer_size = cam.acq_buffer_size()?;
    cam.set_acq_buffer_size(buffer_size * 4)?;
    cam.set_buffers_queue_size(cam.buffers_queue_size_maximum()?)?;

    let mut pre_buffer: BoundedVecDeque<ImageData> = BoundedVecDeque::new(fps as usize);
    let mut post_buffer: BoundedVecDeque<ImageData> = BoundedVecDeque::new(2 * fps as usize);
    let mut num_iterations = 0;
    let mut total_duration = Duration::new(0, 0);

    // Start acquisition
    let buffer = cam.start_acquisition()?;

    for _i in 0..(10 * fps as usize) {
        if _i % 1000 == 0 {
            println!("Iteration: {}", _i);
        }

        let start_time = Instant::now();
        let frame = buffer.next_image::<u8>(None)?;
        let width = frame.width();
        let height = frame.height();
        let nframe = frame.nframe();
        let acq_nframe = frame.acq_nframe();
        let timestamp_raw = frame.timestamp_raw();

        let image_data = ImageData {
            data: ImageBuffer::<Luma<u8>, Vec<u8>>::from(frame),
            width,
            height,
            nframe,
            acq_nframe,
            timestamp_raw,
        };

        // Buffer management
        if pre_buffer.len() < pre_buffer.max_len() {
            pre_buffer.push_back(image_data); // Add to first buffer while it's not full
        } else if post_buffer.len() < post_buffer.max_len() {
            post_buffer.push_back(image_data); // Add to second buffer while it's not full
        } else {
            // concatenate both buffers when both are full
            let mut pre_buffer = pre_buffer.drain(..).collect::<Vec<ImageData>>();
            let mut post_buffer = post_buffer.drain(..).collect::<Vec<ImageData>>();
            pre_buffer.append(&mut post_buffer);
            tx.send(pre_buffer).unwrap();
            break;
        }

        let end_time = Instant::now();
        let iteration_duration = end_time - start_time;
        total_duration += iteration_duration;
        num_iterations += 1;
    }

    println!("Stopping acquisition");
    // unsafe { xiapi_sys::xiStopAcquisition(cam) };
    buffer.stop_acquisition()?;

    let average_duration = total_duration / num_iterations;
    println!("Average duration: {:?}", average_duration);
    println!(
        "Average framerate: {:?}",
        1.0 / average_duration.as_secs_f64()
    );

    println!("Waiting for thread to finish");
    handle.join().expect("Failed to join thread");
    Ok(())
}
