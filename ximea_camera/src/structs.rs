use clap::Parser;
use image::{ImageBuffer, Luma};
use serde::{Deserialize, Serialize};
use std::sync::Arc;

#[derive(Parser, Debug)]
#[command(version, about, long_about = None)]
pub struct Args {
    #[arg(long, default_value_t = 0)]
    pub serial: u32,

    #[arg(long, default_value_t = 250.0)]
    pub fps: f32,

    #[arg(long, default_value_t = 4000.0)]
    pub exposure: f32,

    #[arg(long, default_value_t = 3424)]
    pub width: u32,

    #[arg(long, default_value_t = 3424)]
    pub height: u32,

    #[arg(long, default_value_t = 0.5)]
    pub t_before: f32,

    #[arg(long, default_value_t = 1.0)]
    pub t_after: f32,

    #[arg(long, default_value_t = String::from("127.0.0.1:5555"))]
    pub address: String,
}

#[derive(Clone)]
pub struct ImageData {
    pub data: ImageBuffer<Luma<u8>, Vec<u8>>,
    pub width: u32,
    pub height: u32,
    pub nframe: u32,
    pub acq_nframe: u32,
    pub timestamp_raw: u64,
}

#[allow(non_snake_case)]
#[derive(Serialize, Deserialize, Debug, Default, Copy, Clone)]
#[serde(default)]
pub struct KalmanEstimateRow {
    pub obj_id: u32,
    pub frame: u64,
    pub timestamp: f64,
    pub x: f64,
    pub y: f64,
    pub z: f64,
    pub xvel: f64,
    pub yvel: f64,
    pub zvel: f64,
    pub P00: f64,
    pub P01: f64,
    pub P02: f64,
    pub P11: f64,
    pub P12: f64,
    pub P22: f64,
    pub P33: f64,
    pub P44: f64,
    pub P55: f64,
}

// Adjusted for the enum
pub enum Packet {
    Images(Vec<Arc<ImageData>>),
    Kill,
}
