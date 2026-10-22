#define direction 8
#define step 9
#define enable 10
#define limitTop 13
#define limitBot 12

// Direction pin levels — flip these if UP/DOWN move the wrong way
#define DIR_UP   HIGH
#define DIR_DOWN LOW

int microSecondsDelay = 400;  // Delay between each step edge (controls speed)

long currentPos = 0;   // running step count, mirrors Python's arduino.position
int currentScreen = 1; // which diffuser/screen is currently selected


void setup() {
  // sets up pins as outputs to the TMC2209 driver
  pinMode(direction, OUTPUT);
  pinMode(step, OUTPUT);
  pinMode(enable, OUTPUT);
  pinMode(limitTop, INPUT_PULLUP);
  pinMode(limitBot, INPUT_PULLUP);

  // activates driver (TMC2209 EN is active-LOW)
  digitalWrite(enable, LOW);

  // sends voltage to the direction pin
  digitalWrite(direction, DIR_UP);

  Serial.begin(9600); // Make sure it's the same baud rate as the Python side!
}

void loop() {
  if (Serial.available() > 0) {
    String command = Serial.readStringUntil('\n');
    command.trim();
    handleCommand(command);
  }
}


void handleCommand(String command) {
  if (command.startsWith("UP")) {
    int steps = command.substring(3).toInt();  // text after "UP "
    long moved = stepMotor(steps, DIR_UP, limitTop);
    Serial.print("OK: moved up ");
    Serial.println(moved);
  }
  else if (command.startsWith("DOWN")) {
    int steps = command.substring(5).toInt();  // text after "DOWN "
    long moved = stepMotor(steps, DIR_DOWN, limitBot);
    Serial.print("OK: moved down ");
    Serial.println(moved);
  }
  else if (command.startsWith("HOME")) {
    // Step down repeatedly (a large, safely-oversized count) until the
    // bottom limit switch trips — stepMotor() stops early on its own.
    long moved = stepMotor(50000, DIR_DOWN, limitBot);
    Serial.print("OK: homed after ");
    Serial.println(moved);
  }
  else if (command == "SWITCH") {
    // TODO: replace with your real screen-swap move (e.g. a fixed number
    // of steps to slide the second diffuser/screen into the beam path).
    currentScreen = (currentScreen == 1) ? 2 : 1;
    Serial.print("OK: switched to screen ");
    Serial.println(currentScreen);
  }
  else {
    Serial.println("ERR: unknown command");
  }
}


// Pulses the STEP pin `steps` times in direction `dirLevel`, stopping early
// if `limitPin` is triggered. Reports LIMIT_BOTTOM/LIMIT_TOP so the Python
// side can zero (or flag) its tracked position. Returns steps actually taken.
long stepMotor(int steps, int dirLevel, int limitPin) {
  digitalWrite(direction, dirLevel);
  delayMicroseconds(5); // TMC2209 needs a short setup time after DIR changes

  long taken = 0;
  bool hitLimit = false;
  for (int i = 0; i < steps; i++) {
    if (digitalRead(limitPin) == LOW) {
      hitLimit = true;
      break; // limit switch triggered — stop early
    }
    digitalWrite(step, HIGH);
    delayMicroseconds(microSecondsDelay);
    digitalWrite(step, LOW);
    delayMicroseconds(microSecondsDelay);
    taken++;
  }

  currentPos += (dirLevel == DIR_UP) ? taken : -taken;

  if (hitLimit) {
    if (limitPin == limitBot) {
      currentPos = 0; // bottom switch is the known-zero reference point
      Serial.println("LIMIT_BOTTOM");
    } else {
      Serial.println("LIMIT_TOP");
    }
  }

  return taken;
}
