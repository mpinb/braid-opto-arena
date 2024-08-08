const int stimulusPin = 10;  // Pin to output the stimulus

/**
 * Initializes the setup for the program.
 *
 * @return void
 *
 * @throws None
 */
void setup() {
  Serial.begin(9600);  // Initialize serial communication
  pinMode(stimulusPin, OUTPUT);
}

/**
 * Parse the input string, extract duration, power, and frequency values,
 * and generate a stimulus based on the extracted values.
 *
 * @param None
 *
 * @return None
 *
 * @throws None
 */
void loop() {
  if (Serial.available() > 0) {
    String input = Serial.readStringUntil('\n');
    
    // Parse input string
    int commaIndex1 = input.indexOf(',');
    int commaIndex2 = input.indexOf(',', commaIndex1 + 1);
    
    if (commaIndex1 != -1 && commaIndex2 != -1) {
      int duration = input.substring(0, commaIndex1).toInt();
      int power = input.substring(commaIndex1 + 1, commaIndex2).toInt();
      int frequency = input.substring(commaIndex2 + 1).toInt();
      
      // Generate stimulus
      generateStimulus(duration, power, frequency);
    }
  }
}

/**
 * Generates a stimulus with the specified duration, power, and frequency.
 *
 * @param duration The duration of the stimulus in milliseconds.
 * @param power The power level of the stimulus.
 * @param frequency The frequency of the stimulus in Hz.
 *
 * @throws None
 */
void generateStimulus(int duration, int power, int frequency) {
  if (frequency == 0) {
    // For frequency 0, output constant voltage
    analogWrite(stimulusPin, power);
    delay(duration);
    analogWrite(stimulusPin, 0);
  } else {
    unsigned long startTime = millis();
    unsigned long period = 1000 / frequency;  // Period in milliseconds
    
    while (millis() - startTime < duration) {
      analogWrite(stimulusPin, power);
      delayMicroseconds(period * 500);  // 50% duty cycle
      analogWrite(stimulusPin, 0);
      delayMicroseconds(period * 500);
    }
  }
  
  analogWrite(stimulusPin, 0);  // Ensure the pin is off after the stimulus
}
