#define direction 8
#define step 9
#define enable 10
#define limitTop 13
#define limitBot 12

int noOfSteps = 10000;           // Number of steps to move in each direction
int microSecondsDelay = 400;  // Delay in microseconds between each step


void setup() {
  // put your setup code here, to run once:

  //sets up pins as ouptuts to thte driver
  pinMode(direction, OUTPUT);
  pinMode(step, OUTPUT);
  pinMode(enable, OUTPUT);
  pinMode(limitTop, INPUT_PULLUP);
  pinMode(limitBot, INPUT_PULLUP);

  // activates driver
  digitalWrite(enable, LOW);

  // sends voltage to the direction pin
  digitalWrite(direction, LOW);

  Serial.begin(9600); // Make sure it's the same serial!

  bool limitReported = false;
}

void loop() {
  if (Serial.available() > 0) {
    String command = Serial.readStringUntil('\n');
    command.trim();
    handleCommand(command);
  }

}


void handleCommand(String command) {
  if (digitalRead(limit) == LOW) {
    if (!limitReported) {
        Serial.println("LIMIT_BOTTOM");
        limitReported = true;
    }
      return;
  } 
  else {
    limitReported = false;
  }

  if (command.startsWith("UP")) {
    int steps = command.substring(3).toInt();  // text after "UP "
    digitalWrite(steps, HIGH);
    delayMicroseconds(microSecondsDelay);
  } 
  else if (command.startsWith("DOWN")) {
    int steps = command.substring(5).toInt();  // text after "DOWN "
    digitalWrite(step, LOW);
    delayMicroseconds(microSecondsDelay);
  }
  else if (command.startsWith("HOME")) {
    while (digitalRead(limit) != LOW) {
      digitalWrite(5, LOW);
      delayMicroseconds(microSecondsDelay);
    }
  }
  else if (command == "SWITCH") {
    # if screen 1 move ....
    # if screen 2 move ....
  }
  else {
    Serial.println("ERR: unknown command");
  }
}
