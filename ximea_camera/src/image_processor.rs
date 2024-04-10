use crate::KalmanEstimateRow;

use super::structs::{ImageData, MessageType, Packet};
use crossbeam::channel::Receiver;
use image::ImageFormat;
use rayon::prelude::*;
use std::collections::VecDeque;
use std::fs::create_dir_all;
use std::path::{Path, PathBuf};
use std::sync::Arc;

use std::io::Write;

use std::fs::OpenOptions;

fn save_images_to_disk(
    images: &Vec<Arc<ImageData>>,
    save_path: &PathBuf,
) -> Result<(), Box<dyn std::error::Error>> {
    // loop over images and save to disk
    images.into_par_iter().for_each(|image| {
        // set the filename to save the image to (based on the acq_nframe field of the image)
        let filename = save_path.join(format!("{}.tiff", image.acq_nframe));

        // save the image to disk
        match image.data.save_with_format(&filename, ImageFormat::Tiff) {
            // print a debug message if the image was saved successfully
            Ok(_) => log::debug!("Saved {}", filename.display()),
            // print an error message if the image failed to save
            Err(e) => eprintln!("Failed to save {}: {}", filename.display(), e),
        }
    });

    Ok(())
}

fn save_video_metadata(
    images: &Vec<Arc<ImageData>>,
    save_path: &PathBuf,
) -> Result<(), Box<dyn std::error::Error>> {
    // Open a file in write mode to save CSV data
    //let file = File::create(save_path.join("metadata.csv")).unwrap();
    let mut file = OpenOptions::new()
        .create_new(true)
        .write(true)
        .append(true)
        .open(save_path.join("metadata.csv"))
        .unwrap();

    writeln!(file, "width,height,nframe,acq_nframe,timestamp_raw").unwrap();

    // loop over data
    for (_index, image) in images.iter().enumerate() {
        // Format other data as a line in a CSV file
        let line = format!(
            "{},{},{},{},{}\n",
            image.width, image.height, image.nframe, image.acq_nframe, image.timestamp_raw
        );
        // Write the line to the file
        writeln!(file, "{}", line).unwrap();
    }

    Ok(())
}
pub fn process_packets(
    save_folder: String,
    receiver: Receiver<(Packet, KalmanEstimateRow)>,
) -> Result<(), std::io::Error> {
    // create the save folder if it doesn't exist
    let save_path = Path::new(&save_folder);
    if !save_path.exists() {
        create_dir_all(&save_path)?;
    }

    // loop over packets and save images to disk
    while let Ok((packet, row)) = receiver.recv() {
        // match the packet type
        match packet {
            // if its an images packet, save the images to disk
            Packet::Images(images) => {
                // create new folder with the format row.frame, row.obj_id at save_path
                let save_path =
                    save_path.join(format!("obj_id_{}_frame_{}", row.obj_id, row.frame));
                if !save_path.exists() {
                    create_dir_all(&save_path)?;
                }

                // save all images to disk as tiff
                save_images_to_disk(&images, &save_path).unwrap();

                // save all the metadata from the images to disk
                save_video_metadata(&images, &save_path).unwrap();
            }

            // if its a kill packet, print a message and break the loop
            Packet::Kill => {
                log::info!("Kill signal received, stopping.");
                break;
            }
        }
    }

    Ok(())
}


pub fn frame_handler(receiver: Receiver<(Arc<ImageData>, MessageType)>, n_before: usize, n_after: usize) {
    
    // start frames writing thread
    

    // define control variables
    let mut frame_buffer: VecDeque<Arc<ImageData>> = VecDeque::new();
    let max_length = n_before + n_after;
    let mut switch = false;
    let mut counter = n_after;

    loop {

        // get data
        let (image_data, incoming) = receiver.recv().unwrap();

        match incoming {
            MessageType::JsonData(kalman_row) => {
                // do something with the kalman row
            }
            MessageType::Text(message) => {
                // do something with the text message
            }
            MessageType::Empty => {
                // do something with the empty message
            }
        }
        
        // pop front if buffer is full, and add to buffer
        if frame_buffer.len() == max_length {
            frame_buffer.pop_front();
        }
        frame_buffer.push_back(image_data);

        // if the switch is defined (meaning, we are recording a video)
        if switch {

            // susbtract counter by 1
            counter -= 1;

            // if counter reaches zero, it means we captured enough frames
            if counter == 0 {
                // write frames to disk
                
                // and reset counter and switch
                counter = n_after;
                switch = false;
            }
        }
    }
}