std_msgs/Header header
uint8 drone_id
string mode
bool armed
float32 battery_voltage
float32 battery_percentage
geometry_msgs/PoseStamped pose
geometry_msgs/TwistStamped twist
sensor_msgs/NavSatFix gps
float32 gps_hdop
uint8 satellites_visible
bool ekf_ok

uint8 STATUS_OK = 0
uint8 STATUS_WARN = 1
uint8 STATUS_FAIL = 2
uint8 status
string status_message
