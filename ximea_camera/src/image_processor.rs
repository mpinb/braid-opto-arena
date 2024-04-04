use super::structs::{ImageData, Packet};
use crossbeam::channel::Receiver;
use rayon::prelude::*;
use std::fs::create_dir_all;
use std::path::Path;
use std::sync::Arc; // Make sure this is imported correctly

pub fn process_packets(
    save_folder: String,
    receiver: Receiver<Packet>,
) -> Result<(), std::io::Error> {
    let save_path = Path::new(&save_folder);
    if !save_path.exists() {
        create_dir_all(&save_path)?;
    }

    while let Ok(packet) = receiver.recv() {
        match packet {
            Packet::Images(images) => {
                images.into_par_iter().for_each(|image| {
                    let filename = save_path.join(format!("{}.tiff", image.acq_nframe));

                    match image.data.save(&filename) {
                        Ok(_) => println!("Saved {}", filename.display()),
                        Err(e) => eprintln!("Failed to save {}: {}", filename.display(), e),
                    }
                });
            }
            Packet::Kill => {
                println!("Kill signal received, stopping.");
                break;
            }
        }
    }

    Ok(())
}
