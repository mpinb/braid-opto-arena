use crate::KalmanEstimateRow;

use super::structs::{ImageData, Packet};
use crossbeam::channel::Receiver;
use rayon::prelude::*;
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
        match image.data.save(&filename) {
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
                let save_path = save_path.join(format!("{}_{}", row.frame, row.obj_id));
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
