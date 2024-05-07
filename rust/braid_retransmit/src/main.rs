use chrono::prelude::*;
use futures_util::StreamExt;
use reqwest_eventsource::{Event, EventSource};
use std::collections::HashMap;
use std::time::Instant;
#[tokio::main]
async fn main() {
    // set RUST_LOG to debug, if it's not already set
    if std::env::var("RUST_LOG").is_err() {
        std::env::set_var("RUST_LOG", "info");
    }

    // Initialize logger
    env_logger::init();

    let mut es = EventSource::get("http://10.40.80.6:8397/events");

    // let mut msg: serde_json::Value = serde_json::Value::default();
    let mut curr_obj_id: i64 = 0;
    let mut obj_birth_times: HashMap<i64, Instant> = HashMap::new();

    while let Some(event) = es.next().await {
        // get current timestamp
        let tcall = Instant::now();

        // get message from event
        match event {
            Ok(Event::Open) => println!("Connection Open!"),
            Ok(Event::Message(message)) => {
                // parse message
                let msg: serde_json::Value = serde_json::from_str(&message.data).unwrap();

                // check if message is Birth, Update, or Death
                let has_birth = msg["msg"].get("Birth").is_some();
                let has_update = msg["msg"].get("Update").is_some();
                let has_death = msg["msg"].get("Death").is_some();

                // handle message
                if has_birth {
                    // get obj_id
                    let curr_obj_id = msg["msg"]["Birth"]["obj_id"].as_i64().unwrap();

                    // get the "birth" time of the object
                    obj_birth_times.insert(curr_obj_id, tcall);

                    log::info!(
                        "Birth {}\t\t (at {})",
                        curr_obj_id,
                        Local::now().format("%H:%M:%S%.3f").to_string()
                    );
                } else if has_update {
                    curr_obj_id = msg["msg"]["Update"]["obj_id"].as_i64().unwrap(); // get obj_id

                    // insert to obj_birth_times if not already there
                    obj_birth_times.entry(curr_obj_id).or_insert(tcall);

                    log::debug!("Update: {:?}", msg["msg"]["Update"]["obj_id"]) //debug
                } else if has_death {
                    curr_obj_id = msg["msg"]["Death"].as_i64().unwrap(); // get obj_id
                    log::info!(
                        "Death {} after {} seconds (at {})",
                        curr_obj_id,
                        tcall
                            .duration_since(obj_birth_times[&curr_obj_id])
                            .as_secs(),
                        Local::now().format("%H:%M:%S%.3f").to_string()
                    ); // debug
                    obj_birth_times.remove(&curr_obj_id).unwrap(); // remove from obj_birth_times list
                } else {
                    println!("Unknown message: {:?}", msg);
                }

                log::debug!("obj_ids: {:?}", obj_birth_times);
            }
            Err(err) => {
                println!("Error: {}", err);
                es.close();
            }
        };
    }
}
