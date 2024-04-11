use futures_util::StreamExt;
use reqwest_eventsource::{Event, EventSource};
use std::collections::HashMap;
use std::{hash::Hash, time::Instant};

#[tokio::main]
async fn main() {
    let mut es = EventSource::get("http://10.40.80.6:8397/events");
    let mut tcall = Instant::now();

    let mut curr_obj_id: i64 = 0;
    let mut obj_ids: Vec<i64> = vec![];
    let mut obj_birth_times: HashMap<i64, Instant> = HashMap::new();

    while let Some(event) = es.next().await {
        tcall = Instant::now();

        match event {
            Ok(Event::Open) => println!("Connection Open!"),
            Ok(Event::Message(message)) => {
                let msg: serde_json::Value = serde_json::from_str(&message.data).unwrap();

                let has_birth = msg["msg"].get("Birth").is_some();
                let has_update = msg["msg"].get("Update").is_some();
                let has_death = msg["msg"].get("Death").is_some();

                if has_birth {
                    curr_obj_id = msg["msg"]["Birth"]["obj_id"].as_i64().unwrap();
                    obj_ids.push(curr_obj_id);
                    obj_birth_times.insert(curr_obj_id, Instant::now());
                } else if has_update {
                    curr_obj_id = msg["msg"]["Update"]["obj_id"].as_i64().unwrap();
                    if !obj_birth_times.contains_key(&curr_obj_id) {
                        obj_ids.push(curr_obj_id);
                        obj_birth_times.insert(curr_obj_id, Instant::now());
                    }
                } else if has_death {
                    curr_obj_id = msg["msg"]["Death"].as_i64().unwrap();
                    if obj_birth_times.contains_key(&curr_obj_id) {
                        obj_birth_times.remove(&curr_obj_id);
                    }
                } else {
                    println!("Unknown message: {:?}", msg);
                }
            }
            Err(err) => {
                println!("Error: {}", err);
                es.close();
            }
        }
    }
}
