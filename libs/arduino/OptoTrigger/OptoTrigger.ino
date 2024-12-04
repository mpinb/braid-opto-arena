// Arduino side
const int OUTPUT_PIN = 13;  // Pin to trigger on detection
unsigned long sync_offset = 0;

// Control parameters
struct Parameters {
  float frequency;    // Hz (0-100)
  uint16_t duration; // ms (0-1000)
  uint8_t intensity; // PWM value (0-255)
  uint8_t sham_rate; // Percentage of sham trials (0-100)
} params;

// Timing variables for frequency control
unsigned long last_toggle = 0;
bool output_state = false;
unsigned long trigger_start = 0;
bool trigger_active = false;

void setup() {
  Serial.begin(115200);
  pinMode(OUTPUT_PIN, OUTPUT);
  randomSeed(analogRead(0));  // Initialize random number generator
  
  // Default parameters
  params.frequency = 1.0;    // 1 Hz
  params.duration = 100;     // 100 ms
  params.intensity = 255;    // Full intensity
  params.sham_rate = 0;      // 0% sham trials by default
}

void handleTrigger() {
  unsigned long current_time = millis();
  
  if (trigger_active) {
    // Calculate period in milliseconds from frequency
    unsigned long period = (1000.0 / params.frequency);
    
    // Check if we should toggle based on frequency
    if (current_time - last_toggle >= period/2) {  // Divide by 2 for on/off cycle
      output_state = !output_state;
      analogWrite(OUTPUT_PIN, output_state ? params.intensity : 0);
      last_toggle = current_time;
    }
    
    // Check if trigger duration has elapsed
    if (current_time - trigger_start >= params.duration) {
      trigger_active = false;
      analogWrite(OUTPUT_PIN, 0);
    }
  }
}

void loop() {
  handleTrigger();  // Handle any active triggers
  
  if (Serial.available()) {
    String command = Serial.readStringUntil('\n');
    
    if (command == "SYNC") {
      // Respond with current Arduino timestamp
      Serial.println(millis());
    }
    else if (command.startsWith("PARAM ")) {
      // Parse parameters: "PARAM freq,duration,intensity,sham_rate"
      String param_str = command.substring(6);
      int first_comma = param_str.indexOf(',');
      int second_comma = param_str.indexOf(',', first_comma + 1);
      int third_comma = param_str.indexOf(',', second_comma + 1);
      
      float new_freq = param_str.substring(0, first_comma).toFloat();
      uint16_t new_dur = param_str.substring(first_comma + 1, second_comma).toInt();
      uint8_t new_int = param_str.substring(second_comma + 1, third_comma).toInt();
      uint8_t new_sham = param_str.substring(third_comma + 1).toInt();
      
      // Validate parameters
      if (new_freq >= 0 && new_freq <= 100 &&
          new_dur >= 0 && new_dur <= 1000 &&
          new_int >= 0 && new_int <= 255 &&
          new_sham >= 0 && new_sham <= 100) {
        params.frequency = new_freq;
        params.duration = new_dur;
        params.intensity = new_int;
        params.sham_rate = new_sham;
        Serial.println("OK");
      } else {
        Serial.println("ERROR: Invalid parameters");
      }
    }
    else if (command.startsWith("DETECT ")) {
      // Extract detection timestamp
      unsigned long detection_time = command.substring(7).toInt();
      
      // Determine if this should be a sham trial
      bool is_sham = (random(100) < params.sham_rate);
      
      // Start the trigger (unless it's a sham trial)
      if (!is_sham) {
        trigger_active = true;
        trigger_start = millis();
        last_toggle = trigger_start;
        output_state = true;
        analogWrite(OUTPUT_PIN, params.intensity);
      }
      
      // Calculate execution time in same timebase as detection
      unsigned long arduino_time = millis();
      unsigned long execution_time = arduino_time + sync_offset;
      
      // Send back both timestamps and sham status
      Serial.print(detection_time);
      Serial.print(",");
      Serial.print(execution_time);
      Serial.print(",");d
      Serial.println(is_sham ? "SHAM" : "REAL");
    }
    else if (command == "GET_PARAMS") {
      // Return current parameters
      Serial.print(params.frequency, 2);
      Serial.print(",");
      Serial.print(params.duration);
      Serial.print(",");
      Serial.print(params.intensity);
      Serial.print(",");
      Serial.println(params.sham_rate);
    }
  }
}