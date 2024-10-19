#!/usr/bin/env python3

#-------------- Base NAS Script v1.0 beta --------------#
#                                                       #
#   Created by: Marus Alexander (Romania/Europe)        #
#   Contact and bug report: marus.gradinaru@gmail.com   #
#   Website link: http://marus-gradinaru.42web.io       #
#   Donation link: https://revolut.me/marusgradinaru    #
#                                                       #
#-------------------------------------------------------#

# Note: 
#  Currently, the power button has been disabled. After I built the first prototype, I discovered that the power button
#  was not working properly, because of a design flaw. So, I redesigned it, as you can see in the schematics, and now
#  I'm in the process of testing the second version. Please check the website later for the fully functional code.


# ======================== USER INPUT PARAMETERS ===============================

# ----- GPIO pin definitions ----------

RPiChip = '/dev/gpiochip0'

SDReadyPin = 13      # Output                                       Shutdown ready pin number, high = safe to shutdown
SDReqPin   = 26      # Input   Pull-UP     Rising    Bounce=10ms    Shutdown request pin number, low to high = shutdown requested
RpmPin     = 24      # Input   Pull-UP     Falling                  Fan RPM pin 
UAlertPin  = 17      # Input   Pull-DOWN   Rising                   UPS I2C alert pin
NAlertPin  =  4      # Input   Pull-UP                              NAS I2C alert pin 

# ----- NAS settings -------------------

NasName  = 'NAS'     # The name of the shared Samba NasRoot
NasRoot  = '/NAS'    # NAS Root folder where to mount all block devices
NasPerms = 0o2770    # NAS Root folder and mounted drives content permisions (2: setgid bit - all created files inherit NAS group)
NasGroup = 'rpinas'  # NAS permission group name

# ----- Other settings -----------------

SDCountdown = 300    # Low battery shutdown countdown timer (seconds)


# ========================== BASIC SETUP ===================================

import sys, os, time, importlib, subprocess
from datetime import datetime

# --- Color codes -------
RED        = '\033[31m'
GREEN      = '\033[32m'
YELLOW     = '\033[33m'
MAGENTA    = '\033[35m'
CYAN       = '\033[36m'
WHITE      = '\033[37m'
EXCEPT     = '\033[38;5;147m'  # light purple
RESET      = '\033[0m'
EventColor = ['', GREEN, YELLOW, RED]

AppLogFile = '/tmp/rpinas_log.txt'

def LogD(level, msg):
  try:
    with open(AppLogFile, 'a') as appLog:
      DT = datetime.now()
      TimeStamp = '{:02d}:{:02d}:{:02d}, {:02d}-{:02d}-{:04d}'.format(DT.hour, DT.minute, DT.second, DT.day, DT.month, DT.year)
      appLog.write(f'{TimeStamp}  [ Level: {level} ] - {msg}\n')
  except: pass    

LogD(0, 'App started'+'-'*40)

ParamList = sys.argv[1:] 
Debug = False if any(param == '-sys' for param in ParamList) else True
InstDepend = True if any(param.startswith('-install') for param in ParamList) else False

if os.geteuid() != 0:
  if Debug: print("This script must be run as root. Please try again with 'sudo'.")
  sys.exit(1)


# ======================= INSTALL DEPENDENCIES ===============================

def MinVersion(item_ver, min_ver):
  if (min_ver == None) or (min_ver == ''): return True  
  item_parts = list(map(int, item_ver.split('.')))
  min_parts = list(map(int, min_ver.split('.')))
  for i in range(max(len(item_parts), len(min_parts))):
    item_part = item_parts[i] if i < len(item_parts) else 0
    min_part = min_parts[i] if i < len(min_parts) else 0
    if item_part > min_part: return True
    elif item_part < min_part: return False
  return True

def CheckInstImp(item):
  if isinstance(item, list): 
    item_name = item[0]
    min_ver = item[1]
    cmd_purge = ['apt', 'purge', '-y'] + item[2:]
  else:
    item_name = item
    min_ver = ''
    cmd_purge = []
  if item_name.startswith('python3-'): item_name = item_name[8:]  
  try: item_obj = importlib.import_module(item_name)
  except: return False 
  if min_ver != '':
    item_ver = item_obj.__version__
    if not MinVersion(item_ver, min_ver):
      if len(cmd_purge) > 3:
        result = subprocess.run(cmd_purge, capture_output=True, text=True)
        if result.returncode == 0: return False
        else:
          print(YELLOW+f'Error: Cannot remove old version ({item_ver}) of "{item_name}".'+RESET)
          sys.exit(1)
      else:
        print(YELLOW+f'Error: Module "{item_name}" version is {item_ver}. Expected {min_ver}+ !'+RESET)
        sys.exit(1)
  return True

def CheckInstDpkg(item):
  if isinstance(item, list): 
    item_name = item[0]
    min_ver = item[1]
  else:
    item_name = item
    min_ver = ''
  result = subprocess.run(['dpkg', '-l', item_name], capture_output=True, text=True)
  if result.returncode == 0:
    Lines = result.stdout.splitlines()
    for line in Lines:
      words = line.split(maxsplit=2)[:2]
      if (len(words) == 2) and (words[0] == 'ii') and (words[1] == item_name): return True
  return False 

if InstDepend and Debug:
  Installing = False
  try:
    SysDeps = [
      [ CheckInstDpkg, ['apt',  'install', '-y'], ['python3-pip', 'samba', 'samba-common-bin', 'smbclient', 'hdparm', 'smartmontools'] ],
      [ CheckInstImp,  ['apt',  'install', '-y'], ['python3-psutil', 'python3-netifaces', 'python3-pyudev', 'python3-dbus'] ], 
      [ CheckInstImp,  ['pip3', 'install', '--break-system-packages'], [['gpiod',    '2',     'gpiod', 'libgpiod2', 'python3-libgpiod'] ] ] 
    ]                                                                  # to install, min.ver, to remove...    
    print('Checking dependencies...')
    for dlist in SysDeps:
      CheckInstalled = dlist[0];
      for item in dlist[2]:
        item_name = item[0] if isinstance(item, list) else item
        command = dlist[1] + [item_name]
        if not CheckInstalled(item):
          print(f'Installing required dependence: {item_name} ... ', end='', flush=True)
          Installing = True
          result = subprocess.run(command, capture_output=True, text=True)
          if result.returncode == 0: 
            print(GREEN+'Done.'+RESET); Installing = False
            time.sleep(0.6)
          else:
            print(RED+'Failed !'+RESET); Installing = False
            print(YELLOW+f'Error: {result.stderr}'+RESET)
            sys.exit(1)
    print('All dependencies are installed.')        
  except Exception as E:
    if Installing: print(RED+'Failed !'+RESET)
    print(YELLOW+f'Exception: {E}'+RESET)
    sys.exit(1)

LogD(1, 'Passed dependencies install')

# ========================== IMPORT MODULES ==================================

# --- Internal Modules ----------

import os.path, socket, signal, threading, configparser, select, asyncio
import fcntl, struct, re, mmap, grp, pwd, traceback, shutil, pty, requests
from datetime import timedelta

# --- External Modules ----------

import gpiod, psutil, netifaces, pyudev
from smbus2 import SMBus 
from gpiod.line import Edge, Bias, Direction

LogD(2, 'Modules imported')

# ========================== SYSTEM DEFINITIONS  ==============================

# ----- Install Config ------------------

SambaCfgFile   = '/etc/samba/smb.conf'
CrontabCfgFile = '/var/spool/cron/crontabs/root'
RebootCfgFile  = '/etc/systemd/system/systemd-reboot.service.d/99-nas-script-reboot.conf'
PwrOffCfgFile  = '/etc/systemd/system/systemd-poweroff.service.d/99-nas-script-poweroff.conf'
FirmwareFile   = '/boot/firmware/config.txt'

SambaNasCfg    = [f'path = {NasRoot}', 'writeable = yes', 'inherit permissions = yes', 'public = no']
CrontabCfg     = ['@reboot python3 %RunPath%/nas_script.py -sys >/dev/null 2>&1 &']
RebootCfg      = ['ExecStartPre=python3 %RunPath%/nas_script.py -sys -reboot']
PwrOffCfg      = ['ExecStartPre=python3 %RunPath%/nas_script.py -sys -shutdown']
FirmwarePwmCfg = ['dtoverlay=pwm,pin=18,func=2']
FirmwareLedCfg = ['dtoverlay=act-led,gpio=19']
FirmwareCfg    = [FirmwarePwmCfg[0], FirmwareLedCfg[0]]

CrontabDel     = ['nas_script.py']
FirmwareDel    = ['dtoverlay=pwm', 'dtoverlay=act-led']

RebootSec      = 'Service'
PwrOffSec      = 'Service'
FirmwareSec    = 'all'

# ----- I2C Section -----------------------

PicoAddr     = 0x41
IntAddr      = 0x48
HddAddr      = 0x49
ExtAddr      = 0x4F

cmdPowerOff  = b'\xB1\x83\x6A\x4D'
cmdRstReady  = b'\x83\xB1\xC7\xA6'
cmdShdReady  = b'\xB1\x83\x6A\xC7'
cmdReadBat   = b'\xA6\x3D\x81\xF7'
cmdReadTerm  = b'\x52\xE9\x4B\x83'

regCMD       = 0xBD   # write: 4-byte commands / read: nothing
regRTC       = 0x1C   # write: 9-byte packed datetime / read: nothing
regAlert     = 0x7A   # write: nothing / read: 12 bytes (3 x 4-byte registers)
regMain      = 0xE4   # write: nothing / read: 13 bytes
regFanCfg    = 0x58   # write: 11 bytes / read nothing
regSilentCfg = 0x9B   # write: 11 bytes / read nothing
regBatCfg    = 0xD2   # write: 14 bytes / read nothing
regBatLow    = 0xD3   # write: 2 bytes / read nothing
regShdState  = 0xA6   # write: 1 bytes / read nothing

sigContinue  = 0xCC
sigRetry     = 0x33
sigStop      = 0x69

stNone       = b'\x01\x01\x01\x01'
stShdNow     = b'\x57\xDF\x48\x9B'
stShdLow     = b'\x84\x75\xB9\xFD'
stPowerON    = b'\x72\xC4\x9A\x31'
stPowerOFF   = b'\xA9\x27\x13\x4C'
stBatON      = b'\x6E\x24\xA5\xD3'
stBatOFF     = b'\x5A\xE6\x3D\x42'
stBatOver    = b'\x41\xF8\xA5\x27'

# ----- TCP Server commands ---------------

COMP_CMDID    = 0x24
ANDRO_CMDID   = 0x25
RASPI_CMDID   = 0x42

CMD_NONE       = b'\x00\x00\x00\x00'

CMD_RPIREADY   = b'\xDB\x00\x01\x10'
CMD_MESSAGE    = b'\xDB\x00\x01\x11'
CMD_DEVICES    = b'\xDB\x00\x01\x15'
CMD_DINFO      = b'\xDB\x00\x01\x16'
CMD_RTINFO     = b'\xDB\x00\x01\x17'
CMD_SMART      = b'\xDB\x00\x01\x18'
CMD_UNMOUNT    = b'\xDB\x00\x01\x19'
CMD_MOUNT      = b'\xDB\x00\x01\x1A'
CMD_RTISTART   = b'\xDB\x00\x01\x1B'
CMD_RTISTOP    = b'\xDB\x00\x01\x1C'
CMD_NASRST     = b'\xDB\x00\x01\x1D'
CMD_UPSSHD     = b'\xDB\x00\x01\x1E'
CMD_NASSHD     = b'\xDB\x00\x01\x1F'
CMD_ALLSHD     = b'\xDB\x00\x01\x20'
CMD_SLEEP      = b'\xDB\x00\x01\x21'
CMD_SRVRST     = b'\xDB\x00\x01\x22'
CMD_GETBATVI   = b'\xDB\x00\x01\x23'
CMD_UNLOCK     = b'\xDB\x00\x01\x24'
CMD_READPF     = b'\xDB\x00\x01\x25'
CMD_SETLABEL   = b'\xDB\x00\x01\x26'
CMD_SYSLGET    = b'\xDB\x00\x01\x27'
CMD_SYSLCLR    = b'\xDB\x00\x01\x28'
CMD_GETUPSTERM = b'\xDB\x00\x01\x29'
CMD_GETNASTERM = b'\xDB\x00\x01\x2A'
CMD_CNTDOWN    = b'\xDB\x00\x01\x2B'
CMD_THEEND     = b'\xDB\x00\x01\x2C'
CMD_UPSRST     = b'\xDB\x00\x01\x2D'
CMD_INSTCHECK  = b'\xDB\x00\x01\x2E'
CMD_GETAPM     = b'\xDB\x00\x01\x2F'

CMD_FAILED     = b'\xDB\x00\x02\x01'
CMD_SUCCESS    = b'\xDB\x00\x02\x02'
CMD_TESTMSG    = b'\xDB\x00\x02\x03'
CMD_SETNETCFG  = b'\xDB\x00\x02\x04'
CMD_SETNOTCFG  = b'\xDB\x00\x02\x05'
CMD_SETSTBCFG  = b'\xDB\x00\x02\x07'
CMD_SETNFANCFG = b'\xDB\x00\x02\x08'
CMD_SETUFANCFG = b'\xDB\x00\x02\x09'
CMD_SETSILCFG  = b'\xDB\x00\x02\x0A'
CMD_SETBATCFG  = b'\xDB\x00\x02\x0B'
CMD_SETBATLOW  = b'\xDB\x00\x02\x0C'
CMD_SETAPMCFG  = b'\xDB\x00\x02\x0D'
CMD_GETSMBPATH = b'\xDB\x00\x02\x0E'

CMD_STDOUTBUFF = b'\xDB\x00\x03\x01'
CMD_STDINBUFF  = b'\xDB\x00\x03\x02'
CMD_TERMABORT  = b'\xDB\x00\x03\x03'
CMD_UPGRADE    = b'\xDB\x00\x03\x10'
CMD_REPAIRFS   = b'\xDB\x00\x03\x11'
CMD_CHECKSTB   = b'\xDB\x00\x03\x12'
CMD_SMBSTOP    = b'\xDB\x00\x03\x13'
CMD_SMBSTART   = b'\xDB\x00\x03\x14'
CMD_SMBRESTART = b'\xDB\x00\x03\x15'
CMD_SMBSTATUS  = b'\xDB\x00\x03\x16'

CMD_DEBUG1     = b'\xDB\x00\x10\x01'

CMD_SETTOKEN   = b'\xDB\x00\x20\x01'
CMD_SETLINK    = b'\xDB\x00\x20\x02'
CMD_GETAMPOOL  = b'\xDB\x00\x20\x03' 


# ----- Main Exit -------------------------

exNone        = 0
exRestartNAS  = 1
exShutdownNAS = 2
exRestartUPS  = 3
exShutdownUPS = 4
exShutdownALL = 5

ExitStr = ['exNone', 'exRestartNAS', 'exShutdownNAS', 'exRestartUPS', 'exShutdownUPS', 'exShutdownALL']

# ----- Other constants -------------------

# ----- Notifications ----------------------

OnlineMsg     = 0
RebootMsg     = 1
ShutdownMsg   = 2
AppTermMsg    = 3
HddPark1Msg   = 4
HddPark0Msg   = 5
MainLostMsg   = 6
MainAvailMsg  = 7
BatLowMsg     = 8
BatSafeMsg    = 9
BatLostMsg    = 10
BatAvailMsg   = 11
BatOvr1Msg    = 12
BatOvr0Msg    = 13

BrdMsg = [
 'Raspberry Pi is back online: Main is {}, Batt is {}',
 'Raspberry Pi is rebooting...',
 'Raspberry Pi has been shut down !',
 'Raspberry App has been terminated ({}).',
 'All hard drives were successfully powered off: {}',
 'Error while powering off device {}:\n{}',
 'Warning: Main power is lost !',
 'Main power is now available.',
 'Warning: Battery voltage is low !',
 'Battery voltage is now at a safe level.',
 'Warning: Battery has been disconnected !',
 'The battery has been reconnected.',
 'Warning: Battery overvoltage detected !',
 'Battery voltage is now at a safe level.']

SrvResetStr     = 'The Raspberry server was restarted.'
PowerFailureMsg = 'Warning: power failure detected !'

# ----- Default Settings -------------------

DefaultSettings = """
[General]
FirstSysRun = true

[Network]
CompIP = none
CompPort = 0
RaspiIP = none
RaspiPort = 60303

[Firebase]
AppToken = none
FCMLink = none

[Notifications]
Online.comp = yes
Online.push = no
Online.log = no
Reboot.comp = yes
Reboot.push = no
Reboot.log = no
Shutdown.comp = yes
Shutdown.push = yes
Shutdown.log = no
AppTerm.comp = yes
AppTerm.push = yes
AppTerm.log = no
HddPark.comp = yes
HddPark.push = no
HddPark.log = no
MainLost.comp = yes
MainLost.push = yes
MainLost.log = yes
MainAvail.comp = yes
MainAvail.push = yes
MainAvail.log = yes
BatLow.comp = yes
BatLow.push = yes
BatLow.log = no
BatSafe.comp = yes
BatSafe.push = yes
BatSafe.log = no
BatLost.comp = yes
BatLost.push = yes
BatLost.log = yes
BatAvail.comp = yes
BatAvail.push = yes
BatAvail.log = yes
BatOvr1.comp = yes
BatOvr1.push = yes
BatOvr1.log = yes
BatOvr0.comp = yes
BatOvr0.push = yes
BatOvr0.log = yes
UseIdle = yes
IdleVal = 10

[Standby]
Enabled = yes
CheckPeriod = 60
Default = 5/30

[StandbyCustom]

[APM]
Enabled = yes
Default = 254

[ApmCustom]

[ApmAvail]

[Cooling]
NasFAuto = yes
NasLowTemp = 3800
NasHighTemp = 4100
NasLowDuty = 20
NasHighDuty = 100
NasFixDuty = 50
UpsFAuto = yes
UpsLowTemp = 3300
UpsHighTemp = 3600
UpsLowDuty = 20
UpsHighDuty = 100
UpsFixDuty = 50

[Silent]
Enabled = yes
StartHour = 22
StartMin = 30
StopHour = 8
StopMin = 0
MaxFDuty = 35

[Samba]
User = none
Pass = none
"""

NotifName = ['Online', 'Reboot', 'Shutdown', 'AppTerm', 'HddPark', 'MainLost', 'MainAvail', 'BatLow', 'BatSafe', 'BatLost', 'BatAvail', 'BatOvr1', 'BatOvr0']
NotifExt  = ['.comp', '.push', '.log']

# ----- CRC 8 table -----------------------

crc8_tab = (
  0, 105, 210, 187, 205, 164, 31, 118, 243, 154, 33, 72, 62, 87, 236, 133,
  143, 230, 93, 52, 66, 43, 144, 249, 124, 21, 174, 199, 177, 216, 99, 10,
  119, 30, 165, 204, 186, 211, 104, 1, 132, 237, 86, 63, 73, 32, 155, 242,
  248, 145, 42, 67, 53, 92, 231, 142, 11, 98, 217, 176, 198, 175, 20, 125,
  238, 135, 60, 85, 35, 74, 241, 152, 29, 116, 207, 166, 208, 185, 2, 107,
  97, 8, 179, 218, 172, 197, 126, 23, 146, 251, 64, 41, 95, 54, 141, 228,
  153, 240, 75, 34, 84, 61, 134, 239, 106, 3, 184, 209, 167, 206, 117, 28,
  22, 127, 196, 173, 219, 178, 9, 96, 229, 140, 55, 94, 40, 65, 250, 147,
  181, 220, 103, 14, 120, 17, 170, 195, 70, 47, 148, 253, 139, 226, 89, 48,
  58, 83, 232, 129, 247, 158, 37, 76, 201, 160, 27, 114, 4, 109, 214, 191,
  194, 171, 16, 121, 15, 102, 221, 180, 49, 88, 227, 138, 252, 149, 46, 71,
  77, 36, 159, 246, 128, 233, 82, 59, 190, 215, 108, 5, 115, 26, 161, 200,
  91, 50, 137, 224, 150, 255, 68, 45, 168, 193, 122, 19, 101, 12, 183, 222,
  212, 189, 6, 111, 25, 112, 203, 162, 39, 78, 245, 156, 234, 131, 56, 81,
  44, 69, 254, 151, 225, 136, 51, 90, 223, 182, 13, 100, 18, 123, 192, 169,
  163, 202, 113, 24, 110, 7, 188, 213, 80, 57, 130, 235, 157, 244, 79, 38)

# ----- Devices Database -------------------

DevList = []  # DevList = array of Disk

# Disk
#  [0] - Device name      (String)
#  [1] - Device path      (String)
#  [2] - Device serial    (String)
#  [3] - Size             (UInt64)
#  [4] - Rotational       (Byte)    0 = unknown, 1 = SSD, 2 = HDD
#  [5] - Drive Status     (-obj-)
#  [6] - Partitions       (-obj-)
#  [7] - APM Available    (Byte)    0 = unknown, 1 = no,  2 = yes

# Drive Status
#  [0] - IO count         (UInt64)
#  [1] - keep alive count (UInt32)  [CheckPeriod multiple]
#  [2] - idle count       (UInt32)  [CheckPeriod multiple]
#  [3] - State code       (Byte)    0 = unknown, 1 = active, 2 = standby
#  [4] - State name       (String)
#  [5] - KAS level
#  [6] - SBT level

# Disk Partition
#  [0] - Device name      (String)
#  [1] - Device path      (String)
#  [2] - Label            (String)
#  [3] - UUID             (String)
#  [4] - File system type (String)
#  [5] - Size             (UInt64)
#  [6] - Mount Point      (-obj-)

# Mount Point
#  [0] - Folder name      (String)
#  [1] - Mount path       (String)
#  [2] - Partition type   (String)
#  [3] - Mount options    (String)

LogD(3, 'All definitions loaded')

# ========================= C L A S S E S ==================================

#------ AverageInt Class ----------------------

class AverageInt:
  def __init__(self, Count):
      if Count < 2: Count = 2
      self.Size = Count
      self.Items = [0] * Count
      self.IntX = 0
      self.FirstAdd = True

  def reset(self, NewSize=0):
      if NewSize < 2: NewSize = self.Size
      self.Size = NewSize
      self.Items = [0.0] * NewSize
      self.IntX = 0
      self.FirstAdd = True

  def add_data(self, value):
      if self.FirstAdd:
        self.Items = [value] * self.Size
        self.FirstAdd = False
      else:
        self.Items[self.IntX] = value
        if self.IntX == len(self.Items) - 1: self.IntX = 0
        else: self.IntX += 1

  def get_avg(self):
      return sum(self.Items) // self.Size


#------ TMP275 Sensor Class --------------------

class TMP275:
  temp_reg  = 0x00
  conf_reg  = 0x01
  tlow_reg  = 0x02
  thig_reg  = 0x03

  def __init__(self, TheI2C, Address, ResBits):
    self.I2C = TheI2C
    self.Addr = Address
    self.Config(ResBits)

  def Config(self, NewResBits):
    self.ResBits = NewResBits
    self.Resolution = 128 / (2 ** (self.ResBits-1))
    self.B2_bits  = self.ResBits - 8
    self.B2_shift = 8 - self.B2_bits
    self.B2_mask  = (2 ** self.B2_bits) - 1
    CONF = ( 0b00010000 | ((self.ResBits - 9) << 5) ) & 0xFF
    with i2cLock: self.I2C.write_byte_data(self.Addr, self.conf_reg, CONF)

  def Temperature(self):
    with i2cLock: raw = self.I2C.read_i2c_block_data(self.Addr, self.temp_reg, 2)
    LSB = ((raw[1] >> self.B2_shift) & self.B2_mask) * self.Resolution
    return int((raw[0]+LSB)*100)

  def GetTempAlert(self, Reg):
    with i2cLock: raw = self.I2C.read_i2c_block_data(self.Addr, Reg, 2)
    LSB = ((raw[1] >> 4) & 0x0F) * self.Resolution
    return round(raw[0]+LSB, 2)

  def SetTempAlert(self, Reg, Value):
    if Value > 127.9375: Value = 127.9375
    Value = int(Value / 0.0625)
    B1 = (Value >> 4) & 0xFF
    B2 = (Value << 4) & 0xF0
    with i2cLock: self.I2C.write_i2c_block_data(self.Addr, Reg, [B1, B2])


#------ Fast Timer Class --------------------

class FastTimer(threading.Thread):
  def __init__(self, interval, callback, args=None, kwargs=None, shots=1, name=None):
    super().__init__(name=name)
    self.daemon = True
    self.interval = interval
    self.callback = callback
    self.args = args if args is not None else []
    self.kwargs = kwargs if kwargs is not None else {}
    self.last_shot = shots
    self.trigger = threading.Event()
    self.done = threading.Event()
    self.terminated = threading.Event()
    self.start()

  def Terminate(self):
    if self.is_alive():
      self.terminated.set()
      self.done.set()
      self.trigger.set()
      self.join()

  def Gooo(self):
    if self.is_alive():
      self.trigger.set()

  def Abort(self):
    if self.is_alive():
      self.done.set()
      self.trigger.clear()

  def Reset(self):
    if self.is_alive():
      self.done.set()

  def Mark(self):
    if self.is_alive():
      if self.trigger.is_set(): self.done.set()
      else: self.trigger.set()

  def run(self):
    while not self.terminated.is_set():
      if not self.trigger.is_set():
        shot = 0; self.done.clear()
      self.trigger.wait()
      Reseted = self.done.wait(self.interval)
      self.done.clear()
      if self.terminated.is_set(): break
      if not Reseted:
        if self.last_shot > 0:
          shot += 1
          if shot == self.last_shot:
            self.trigger.clear()
        self.callback(*self.args, **self.kwargs)


#------ GPIO Pin Monitor Class -------------------

class GpioMonitor(threading.Thread):
  def __init__(self, label, config, callbacks):
    super().__init__(name='GPIO Monitor')
    self.daemon = False
    self.Label = label
    self.LConfig = config
    self.LCallbacks = callbacks
    self.done_fd = os.eventfd(0)
    self.start()

  def Terminate(self):
    if self.is_alive():
      os.eventfd_write(self.done_fd, 1)
      self.join()

  def run(self):
    with gpiod.request_lines(RPiChip, consumer=self.Label, config=self.LConfig) as request:
      poll = select.poll()
      poll.register(request.fd, select.POLLIN)
      poll.register(self.done_fd, select.POLLIN)
      while True:
        for fd, event in poll.poll():
          if fd == self.done_fd: return
          for event in request.read_edge_events():
            if event.line_offset in self.LCallbacks:
              try: self.LCallbacks[event.line_offset](event)
              except: pass


#------ BlockDev Monitor Class --------------------

class BlockDevMonitor(threading.Thread):
  def __init__(self, callback, args=None, kwargs=None):
    import time
    super().__init__(name='Block Devices Monitor')
    self.loop = None
    self.timer = FastTimer(1, callback, args, kwargs, name='Block Devices FastTimer')
    self.start()
    time.sleep(0.3)

  def Terminate(self):
    if self.is_alive():
      if self.loop != None: self.loop.quit()
      self.join()
    self.timer.Terminate()

  def run(self):
    import dbus
    from dbus.mainloop.glib import DBusGMainLoop
    from gi.repository import GLib

    def sigUnitChg(*args):
      if (len(args) >= 1) and ( args[0].startswith('blockdev@') or ('-block-' in args[0]) or (r'-by\x2dlabel-' in args[0]) ): self.timer.Mark()

    if Debug: print('DevMonitor thread started.')
    DBusGMainLoop(set_as_default=True)
    self.loop = GLib.MainLoop()
    bus = dbus.SystemBus()
    bus.add_signal_receiver(sigUnitChg, dbus_interface='org.freedesktop.systemd1.Manager', signal_name='UnitNew', path='/org/freedesktop/systemd1')
    bus.add_signal_receiver(sigUnitChg, dbus_interface='org.freedesktop.systemd1.Manager', signal_name='UnitRemoved', path='/org/freedesktop/systemd1')

    self.loop.run()
    if Debug: print('DevMonitor thread ended.')


#------ Permission Manager Class --------------------

class PermissionManager:
  def __init__(self):
    self.TaskList = []
    self.Access = threading.RLock()
    self.Done = threading.Event()
    self.Done.set()

  def AddTask(self, tg_dev, tg_mpoint):
    with self.Access:
      for i in range(len(self.TaskList)):
        if self.TaskList[i][2] == tg_dev:
          SendMessageToComp(CMD_MESSAGE, f'Please wait ! Already working on permissions on {tg_dev}...', 2)
          return
      end_flag = threading.Event()
      WT = threading.Thread(target=self.WorkThread, args=(tg_mpoint, end_flag), name='Permission Manager')
      self.TaskList.append([WT, end_flag, tg_dev, tg_mpoint])
      self.Done.clear()
      WT.start()

  def Terminate(self):
    with self.Access:
      for i in range(len(self.TaskList)): self.TaskList[i][1].set()
    self.Done.wait()

  def WorkThread(self, mpoint, terminated):
    Commands = [
      [['sudo', 'find', mpoint, '-type', 'd', '-exec', 'chmod', oct(NasPerms)[2:], '--', '{}', '+'], 'dir chmod'],
      [['sudo', 'find', mpoint, '-type', 'f', '-exec', 'chmod', 'ug+rw,g-s', '--', '{}', '+'], 'file chmod'],
      [['sudo', 'chown', '-R', ':'+NasGroup, mpoint], 'chown']]
    SendMessageToComp(CMD_MESSAGE, f'Start setting file permissions for {mpoint}...', 1)
    try:
      for i in range(len(Commands)):
        process = subprocess.Popen(Commands[i][0], stderr=subprocess.PIPE)
        tr_sent = False
        while process.poll() is None:
          if not tr_sent and terminated.is_set():
            process.terminate()
            tr_sent = True
          time.sleep(0.5)
        if process.returncode != 0:
          if terminated.is_set(): SendMessageToComp(CMD_MESSAGE, f'Setting permissions for {mpoint} aborted at: {Commands[i][1]} !', 2)
          else: SendMessageToComp(CMD_MESSAGE, f'Failed setting permisions for {mpoint}: {process.stderr.read().decode("utf-8")}', 3)
          return
      SendMessageToComp(CMD_MESSAGE, f'Setting permissions for {mpoint} completed successfully.', 1)
    except Exception as E:
      SendMessageToComp(CMD_MESSAGE, f'Failed setting permissions for {mpoint}: {E}', 3)
    finally:
      with self.Access:
        CT = threading.current_thread()
        for i in range(len(self.TaskList)):
          if self.TaskList[i][0] == CT:
            del self.TaskList[i]; break
        if len(self.TaskList) == 0: self.Done.set()


#------ Hardware PWM Class --------------------

# pwm0 is GPIO pin 18 is physical pin 32 (dtoverlay can be deployed to use GPIO 12 instead)
# pwm1 is GPIO pin 19 is physical pin 33 (dtoverlay can be deployed to use GPIO 13 instead)

class HardwarePWMException(Exception): pass

class HardwarePWM:
  ChipPath: str = '/sys/class/pwm/pwmchip0'
  DC: float
  Freq: float

  def __init__(self, channel: int, freq: float):
    if channel not in {0, 1}:
      raise HardwarePWMException('Only channel 0 and 1 are available on the Rpi.')
    self.pwm_dir = f'{self.ChipPath}/pwm{channel}'; self.DC = 0
    if not os.path.isdir(self.ChipPath):
      raise HardwarePWMException('PWM overlay is not enabled.')
    if not os.access(self.ChipPath+'/export', os.W_OK):
      raise HardwarePWMException(f'Need write access to files in "{self.ChipPath}"')
    if not os.path.isdir(self.pwm_dir):
      self.echo(channel, f'{self.ChipPath}/export')
    self.SetFreq(freq)

  def echo(self, message: int, filename: str):
    with open(filename, 'w') as file: file.write(f'{message}\n')

  def Start(self, duty_cycle: float):
    self.SetDuty(duty_cycle)
    self.echo(1, f'{self.pwm_dir}/enable')

  def Stop(self):
    self.SetDuty(0)
    self.echo(0, f'{self.pwm_dir}/enable')

  def SetDuty(self, duty_cycle: float):
    if not (0 <= duty_cycle <= 100):
      raise HardwarePWMException('Duty cycle must be between 0 and 100 (inclusive).')
    self.DC = duty_cycle
    per = 1000000000 / float(self.Freq)  # in nanoseconds
    pdc = int(per * duty_cycle / 100)    # in nanoseconds
    self.echo(pdc, f'{self.pwm_dir}/duty_cycle')

  def SetFreq(self, freq: float):
    if freq < 0.1: raise HardwarePWMException('Frequency cannot be lower than 0.1 on the Rpi.')
    self.Freq = freq
    # we first have to change duty cycle, since https://stackoverflow.com/a/23050835/1895939
    BackDC = self.DC
    if self.DC > 0: self.SetDuty(0)
    per = 1000000000 / float(freq)  # in nanoseconds
    self.echo(int(per), f'{self.pwm_dir}/period')
    self.SetDuty(BackDC)


# ========================= F U N C T I O N S ================================

#----- System functions -------------------------

def BootDone():
  res = False
  try:
    result = subprocess.run(['systemctl', 'is-active', 'multi-user.target'], capture_output=True, text=True)
    res = result.stdout.strip() == 'active'
  except Exception as E:
    if Debug: print(f'BootDone Exception: {E}')
  return res

def AlreadyRunning():
  current_pid = os.getpid()
  script_name = os.path.basename(__file__)
  # print(f'CPID: {current_pid}  Name: {script_name}')
  for process in psutil.process_iter(['pid', 'name', 'cmdline']):
    try:
      if 'python' in process.info['name']:
        # print(f'PID: {process.info["pid"]}  Name: {process.info["name"]}  CmdLine: {" ".join(process.info["cmdline"])}')
        if (process.info['pid'] != current_pid) and (script_name in ' '.join(process.info['cmdline'])): return True
    except (psutil.NoSuchProcess, psutil.AccessDenied): continue
  return False

def MainExit(cmd, rsecs = 10):
  global ExitCmd, ExitRSecs, AsyncTerminated
  if not AsyncTerminated:
    ExitCmd = cmd
    ExitRSecs = rsecs
    AsyncTerminated = True
    with upsLock: UPSEvent.set()


def NASMarkSD():
  with open('/tmp/sdtype', 'w') as SDFile:
    SDFile.write('SD-NAS')

def UPSMarkSD():
  with open('/tmp/sdtype', 'w') as SDFile:
    SDFile.write('SD-UPS')

def UPSMarkRS(secs):
  with open('/tmp/sdtype', 'w') as SDFile:
    SDFile.write(f'RS-UPS:{secs}')

def ALLMarkSD():
  with open('/tmp/sdtype', 'w') as SDFile:
    SDFile.write('SD-ALL')

def ShutdownType():
  try:
    with open('/tmp/sdtype', 'r') as SDFile:
      SDT = SDFile.read().strip().split(':')
    if   SDT[0] == 'SD-NAS': return 'SD-NAS', None
    elif SDT[0] == 'RS-UPS': return 'RS-UPS', int(SDT[1])
    elif SDT[0] == 'SD-UPS': return 'SD-UPS', None
    elif SDT[0] == 'SD-ALL': return 'SD-ALL', None
    else: return 'RS-UPS', 10
  except: return 'RS-UPS', 10

def SignalToCutThePower():
  try:
    SDType, RSecs = ShutdownType()
    I2CBus = SMBus(1)
    try:
      if SDType == 'SD-NAS':
        I2CBus.write_i2c_block_data(PicoAddr, regShdState, [1])
        time.sleep(0.5)
      elif SDType == 'SD-ALL':
        I2CBus.write_i2c_block_data(PicoAddr, regCMD, list(cmdPowerOff))
        time.sleep(5)
      elif SDType == 'SD-UPS':
        I2CBus.write_i2c_block_data(PicoAddr, regCMD, list(cmdShdReady))
        time.sleep(5)
      elif SDType == 'RS-UPS':
        I2CBus.write_i2c_block_data(PicoAddr, regCMD, list(cmdRstReady + struct.pack('<H', RSecs)))
        time.sleep(5)
    finally: I2CBus.close()
  except: pass
  SDReadyCfg = { SDReadyPin: gpiod.LineSettings(direction=Direction.OUTPUT) }
  with gpiod.request_lines(RPiChip, consumer="NAS-CutPower", config=SDReadyCfg) as request:
    request.set_value(SDReadyPin, gpiod.line.Value.ACTIVE)
    time.sleep(1)

def PowerOffHDDs():
  disks = []
  for dev in UDEV.list_devices(subsystem='block', DEVTYPE='disk'):
    if re.match(r'sd[a-z]$', dev.sys_name) and RotationalDisk(dev.sys_name):
      disks.append([dev.sys_name, dev.device_node])
  if len(disks) == 0: return
  disks.sort(key=lambda x: x[0])
  devices = ', '.join([disk[0] for disk in disks]); AllOK = True
  for disk in disks: KeepAlive(disk[1])
  time.sleep(5)
  for disk in disks:
    cmd = ['sudo', '/usr/sbin/hdparm', '-y', disk[1]]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if AllOK and result.returncode != 0:
      AllOK = False; ErrMsg1 = disk[1]; ErrMsg2 = result.stderr
  if AllOK: BroadcastMsg(HddPark1Msg, 1, [devices])
  else: BroadcastMsg(HddPark0Msg, 3, [ErrMsg1, ErrMsg2])
  time.sleep(8)

  
def SetSafeShd():
  open(SafeShdFile, 'a').close()

def ClearSafeShd():
  try: os.remove(SafeShdFile)
  except: pass

def WasSafeShd():
  with cfgLock:
    try: FirstRun = Config['General'].getboolean('FirstSysRun')
    except: FirstRun = True 
  return FirstRun or os.path.exists(SafeShdFile)

def PowerFailureMsgHandler():
  global Sshd_Ack
  with pflLock:
    if not Debug and not Sshd_Ack:
      idle = SendMessageToComp(CMD_MESSAGE, PowerFailureMsg, 3)
      if idle >= 0: Sshd_Ack = True  
  

#----- Simple functions -------------------------

def MsgFormat(Msg, Params):
  if Msg.count('{}') == len(Params):
    return Msg.format(*Params)
  else: return None

def rPad(the_str, length):
  the_str = str(the_str)
  if len(the_str) >= length: return the_str
  else: return the_str + ' ' * (length - len(the_str))

def PackSStr(TheStr):
  PS = TheStr.encode('utf-8')
  Size = struct.pack('<B', len(PS))
  return Size + PS

def PackWStr(TheStr):
  PS = TheStr.encode('utf-8')
  Size = struct.pack('<H', len(PS))
  return Size + PS

def PackStr(TheStr):
  PS = TheStr.encode('utf-8')
  Size = struct.pack('<I', len(PS))
  return Size + PS

def UnpackSStr(Buff, Idx):
  Size = struct.unpack('<B', Buff[Idx:Idx+1])[0]
  return Buff[Idx+1:Idx+1+Size].decode('utf-8'), Size+1

def UnpackWStr(Buff, Idx):
  Size = struct.unpack('<H', Buff[Idx:Idx+2])[0]
  return Buff[Idx+2:Idx+2+Size].decode('utf-8'), Size+2

def PackMessage(ts, LID, msg): 
  return struct.pack('<dB', ts, LID) + PackWStr(msg)

def FormatBytes(data):
  return ' '.join(['{:02x}'.format(byte) for byte in data]).upper()

def ShowStatInfo():
  for disk in DevList:
    print(f'{rPad(disk[0]+" =", 8)} IO: {rPad(disk[5][0], 10)} KA: {rPad(disk[5][1], 5)} Idle: {rPad(disk[5][2], 5)} State: {disk[5][4]}  {disk[5][5]}/{disk[5][6]}')
  print('')

def ShowDiskInfo():
  for disk in DevList:
    print(f'Disk: {disk[0]} {disk[1]} {disk[2]} {disk[3]} {disk[4]}')
    for part in disk[6]:
      print(f'  - Part: {part[0]} {part[1]} {part[2]} {part[3]} {part[4]} {part[5]}')
      print(f'          {part[6]}')
  print('')

def ShowAllThreads():
  time.sleep(0.1)  
  process = psutil.Process(os.getpid())
  own_threads = {thread.native_id: thread.name for thread in threading.enumerate()}
  print('----------------------------------------')
  for tinfo in process.threads():
    if tinfo.id in own_threads:
      owned = '[own]'
      name  = own_threads[tinfo.id] 
    else:
      owned = '[sys]'  
      name  = 'Unknown'
    print(f'{owned}  {rPad(tinfo.id, 8)}  {rPad(name, 25)}  User Time: {rPad(tinfo.user_time, 10)}  Sys Time: {rPad(tinfo.system_time, 10)}')
  print('----------------------------------------')  


#----- Script Instalation ------------------------

def GetSection(Lines, section, create=False, whole=False):
  if section == '':
    SS = 0; SE = len(Lines)
  else:
    SS = -1; SE = len(Lines);
    section = '['+section+']'
    for I in range(len(Lines)):
      if SS < 0:
        if Lines[I].strip() == section: SS = I+1
      else:
        if Lines[I].strip().startswith('['):
          SE = I; break
    if SS >= 0:
      if not whole:
        while (SE > SS) and (Lines[SE-1].strip() == ''): SE -= 1
    else:
      if create:
        L = len(Lines) -1
        if (L >= 0) and (Lines[L].strip != ''): Lines.append('\n')
        Lines.append(section+'\n')
        SS = len(Lines); SE = SS
  return SS, SE

def CheckForLines(filename, to_check, section=''):
  try:
    with open(filename, 'r') as file: Lines = file.readlines()
    SS, SE = GetSection(Lines, section)
    if SS < 0: return False
    for line in to_check:
      for I in range(SS, SE):
        if Lines[I].strip() == line: break
      else: return False
    return True  
  except: return False

def ChangeFileLines(filename, to_add, to_clean, section=''):
  try:
    with open(filename, 'r') as file: Lines = file.readlines()
    SS, SE = GetSection(Lines, section, True)
    if isinstance(to_clean, str):
      if to_clean == 'all':
        while SE > SS:
          del Lines[SS]
          SE -= 1
    else:  
      for CL in to_clean:
        for I in range(SE-1, SS-1, -1):
          if CL in Lines[I]:
            del Lines[I]
            SE -= 1        
    for AD in to_add:
      Lines.insert(SE, AD+'\n')
      SE += 1
    with open(filename, 'w') as file: file.writelines(Lines)
    return ''
  except Exception as E:
    return f'{E}'

def RemoveSection(filename, section):
  try:
    with open(filename, 'r') as file: Lines = file.readlines()
    SS, SE = GetSection(Lines, section, whole=True)
    if SS < 0: return ''
    Count = SE-SS+1; SS -= 1;
    for i in range(Count): del Lines[SS]
    with open(filename, 'w') as file: file.writelines(Lines)
    return ''
  except Exception as E:
    return f'{E}'

def GetI2CState():
  try:
    result = subprocess.run(['sudo', 'raspi-config', 'nonint', 'get_i2c'], capture_output=True, text=True, check=True)
    return result.stdout.strip() == '0'
  except: return False

def SetI2CState(state):
  try:
    cmd = '0' if state else '1'
    result = subprocess.run(['sudo', 'raspi-config', 'nonint', 'do_i2c', cmd], capture_output=True, text=True)
    return '' if result.returncode == 0 else result.stderr
  except Exception as E:
    return f'{E}'

def ExtendService(serv, Lines):
  try:
    serv_dir = f'/etc/systemd/system/systemd-{serv}.service.d'
    os.makedirs(serv_dir, exist_ok=True)
    with open(f'{serv_dir}/99-nas-script-{serv}.conf', 'w') as file:
      file.write('[Service]\n')
      for line in Lines: file.write(f'{line}\n')
    return ''
  except Exception as E:
    return f'{E}' 

def RemoveExtension(serv):
  try:
    serv_dir = f'/etc/systemd/system/systemd-{serv}.service.d'
    os.remove(f'{serv_dir}/99-nas-script-{serv}.conf')
    try: os.rmdir(serv_dir)
    except: pass
    return ''
  except Exception as E:
    return f'{E}' 

def SetupSambaNas():
  try:
    the_user = IRNewUser; the_pass = IRNewPass
    SaveCred = (IRNewUser != '') or (IRNewPass != '')
    with cfgLock:
      if the_user == '': the_user = Config['Samba']['User']
      if the_pass == '': the_pass = Config['Samba']['Pass']

    # Stop Samba services
    result = subprocess.run(['systemctl', 'stop', 'smbd', 'nmbd'], capture_output=True, text=True)
    if result.returncode != 0: return 'Cannot stop Samba services:\n'+result.stderr     

    # Create NAS group and add the user in it
    result = subprocess.run(['groupadd', NasGroup], capture_output=True, text=True)
    if (result.returncode != 0) and (not 'already exists' in result.stderr): 
      return 'Cannot create NAS permission group:\n'+result.stderr
    result = subprocess.run(['gpasswd', '-a', the_user, NasGroup], capture_output=True, text=True)
    if (result.returncode != 0): return 'Cannot add user to NAS group:\n'+result.stderr
    
    # Create the NAS root if needed, and setup permissions and ownership 
    ErrMsg = NasSysDir(NasRoot)
    if ErrMsg != '': return 'Cannot setup the NAS root folder:\n'+ErrMsg

    # Configure Samba NAS
    ErrMsg = ChangeFileLines(SambaCfgFile, SambaNasCfg, 'all', NasName)
    if ErrMsg != '': return 'Cannot edit Samba configuration file:\n'+ErrMsg

    # Setup user and password for Samba NAS access
    result = subprocess.run(['smbpasswd', '-x', the_user], capture_output=True, text=True)
    if (result.returncode != 0) and (not 'Failed to find' in result.stderr): 
      return 'Cannot remove the old Samba user:\n'+result.stderr
    command = ['smbpasswd', '-a', the_user]
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    process.communicate(input=(f'{the_pass}\n{the_pass}\n').encode())
    if process.returncode != 0: return 'Cannot configure the new Samba user:\n'+result.stderr

    # Enable Samba services 
    result = subprocess.run(['systemctl', 'is-enabled', 'smbd', 'nmbd'], capture_output=True, text=True)
    state = result.stdout.strip().split('\n')
    if len(state) != 2: return 'Cannot get Samba status:\n'+result.stderr
    command = ['systemctl', 'enable']
    if state[0] != 'enabled': command.append('smbd')
    if state[1] != 'enabled': command.append('nmbd')
    if len(command) > 2:
      result = subprocess.run(command, capture_output=True, text=True)
      if result.returncode != 0: return 'Cannot enable Samba services:\n'+result.stderr

    # Start Samba services
    result = subprocess.run(['systemctl', 'start', 'smbd', 'nmbd'], capture_output=True, text=True)
    if result.returncode != 0: return 'Cannot start Samba services:\n'+result.stderr

    if SaveCred:
      with cfgLock:
        Config['Samba']['User'] = the_user
        Config['Samba']['Pass'] = the_pass
        SaveConfigNow(True)
    return ''
  except Exception as E:
    return f'Unexpected error while setting up Samba:\n{E}' 

def RemoveSambaNas():
  try:
    # Stop Samba services (but not disable it)
    result = subprocess.run(['systemctl', 'stop', 'smbd', 'nmbd'], capture_output=True, text=True)
    if result.returncode != 0: return 'Cannot stop Samba services:\n'+result.stderr     

    # Remove user and password for Samba NAS database
    with cfgLock: the_user = Config['Samba']['User']
    if the_user != '':
      result = subprocess.run(['smbpasswd', '-x', the_user], capture_output=True, text=True)
      if (result.returncode != 0) and (not 'Failed to find' in result.stderr):
        return 'Cannot remove user credentials from Samba database:\n'+result.stderr

    # Remove Samba NAS configuration
    ErrMsg = RemoveSection(SambaCfgFile, NasName)
    if ErrMsg != '': return 'Cannot edit Samba configuration file:\n'+ErrMsg

    return ''
  except Exception as E:
    return f'Unexpected error while removing Samba installation:\n{E}' 

def IsSambaNasReady(CheckAkt=True):
  try:
    the_user = IRNewUser; the_pass = IRNewPass
    with cfgLock:
      if the_user == '': the_user = Config['Samba']['User']
      if the_pass == '': the_pass = Config['Samba']['Pass']

    # Check NAS group existence and user membership
    nas_grp = grp.getgrnam(NasGroup)
    for member in nas_grp.gr_mem:
      if member == the_user: break
    else: return False

    # Check NAS root folder existence, permissions and ownership
    stat_info = os.stat(NasRoot)
    curr_perms = stat_info.st_mode & 0o7777
    curr_owner = pwd.getpwuid(stat_info.st_uid).pw_name
    curr_group = grp.getgrgid(stat_info.st_gid).gr_name
    if (curr_perms != NasPerms) or (curr_owner != 'root') or (curr_group != NasGroup): return False 

    # Checking if Samba is installed, active and service enabled
    if CheckAkt:
      result = subprocess.run(['systemctl', 'is-active', 'smbd', 'nmbd'], capture_output=True, text=True)
      state = result.stdout.strip().split('\n')
      if (len(state) != 2) or (state[0] != 'active') or (state[1] != 'active'): return False
    result = subprocess.run(['systemctl', 'is-enabled', 'smbd', 'nmbd'], capture_output=True, text=True)
    state = result.stdout.strip().split('\n')
    if (len(state) != 2) or (state[0] != 'enabled') or (state[1] != 'enabled'): return False

    # Checking if Samba NAS is configured
    if not CheckForLines(SambaCfgFile, SambaNasCfg, NasName): return False

    # Checking with provided username and password for access
    if CheckAkt:
      command = ['smbclient', f'//{socket.gethostname()}{NasRoot}', '-U', the_user, '-c', 'exit']
      process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
      process.communicate(input=(f'{the_pass}\n').encode())
      if process.returncode != 0: return False

    return True
  except: return False

def GetInstStatus(CheckSmbAkt=True):
  SambaNas      = IsSambaNasReady(CheckSmbAkt)
  RunAtBoot     = CheckForLines(CrontabCfgFile, CrontabCfg)
  RunAtRestart  = CheckForLines(RebootCfgFile, RebootCfg, RebootSec)
  RunAtShutdown = CheckForLines(PwrOffCfgFile, PwrOffCfg, PwrOffSec)
  PWMEnabled    = CheckForLines(FirmwareFile, FirmwarePwmCfg, FirmwareSec)
  LEDEnabled    = CheckForLines(FirmwareFile, FirmwareLedCfg, FirmwareSec)
  I2CEnabled    = GetI2CState()
  return struct.pack('<???????', SambaNas, RunAtBoot, RunAtRestart, RunAtShutdown, PWMEnabled, LEDEnabled, I2CEnabled)

def ShowStatus(stat):
  if len(stat) != 7: return
  Opts = ['Samba NAS is properly configured', 
    'Script configured to run at boot',     'Script configured to run at restart',
    'Script configured to run at shutdown', 'Hardware PWM feature enabled',
    'External AKT LED feature enabled',     'I2C communication feature enabled']
  Opts = ['   [x] '+Opts[I] if stat[I] == 0x01 else '   [ ] '+Opts[I] for I in range(len(stat))]
  for Opt in Opts: print(Opt)

def InstallScript(do_samba, do_paths, do_hwfeat):
  print('Installing NAS script...\n')
  if do_samba: 
    ErrMsg = SetupSambaNas()
    if ErrMsg != '': print(ErrMsg+'\n')
  if do_paths:
    if not os.path.exists(CrontabCfgFile): open(CrontabCfgFile, 'a').close()
    ErrMsg = ChangeFileLines(CrontabCfgFile, CrontabCfg, CrontabDel)
    if ErrMsg != '': print('Cannot configure script to run at boot:\n'+ErrMsg+'\n')
    ErrMsg = ExtendService('reboot', RebootCfg)
    if ErrMsg != '': print('Cannot configure script to run at restart:\n'+ErrMsg+'\n')
    ErrMsg = ExtendService('poweroff', PwrOffCfg)
    if ErrMsg != '': print('Cannot configure script to run at shutdown:\n'+ErrMsg+'\n')
  if do_hwfeat:
    ErrMsg = ChangeFileLines(FirmwareFile, FirmwareCfg, FirmwareDel, FirmwareSec)
    if ErrMsg != '': print('Cannot edit firmware config file:\n'+ErrMsg+'\n')
    ErrMsg = SetI2CState(True)
    if ErrMsg != '': print('Cannot enable I2C feature:\n'+ErrMsg+'\n')
    time.sleep(1)
  Stat = GetInstStatus()
  if all(value == 0x01 for value in Stat):
    print(CYAN+'Status: '+GREEN+'The script was successfully installed.'+RESET)
    if do_hwfeat: print(YELLOW+'Please reboot your system !'+RESET)
  else: 
    print(CYAN+'Status: '+RED+'The script is not fully installed.'+RESET)
    print(YELLOW+'Something went wrong. The script could not be installed properly.'+RESET)
  print('')
  ShowStatus(Stat)

def UninstallScript(do_samba, do_paths, do_hwfeat):
  print('Uninstalling NAS script...\n')
  if do_samba:
    ErrMsg = RemoveSambaNas()
    if ErrMsg != '': print(ErrMsg+'\n')
  if do_paths:  
    ErrMsg = ChangeFileLines(CrontabCfgFile, [], CrontabDel)
    if ErrMsg != '': print('Cannot remove "run at boot" configuration:\n'+ErrMsg+'\n')
    ErrMsg = RemoveExtension('reboot')
    if ErrMsg != '': print('Cannot remove "run at restart" configuration:\n'+ErrMsg+'\n')
    ErrMsg = RemoveExtension('poweroff')
    if ErrMsg != '': print('Cannot remove "run at shutdown" configuration:\n'+ErrMsg+'\n')
  if do_hwfeat:  
    ErrMsg = ChangeFileLines(FirmwareFile, [], FirmwareDel, FirmwareSec)
    if ErrMsg != '': print('Cannot remove firmware configuration:\n'+ErrMsg+'\n')
    ErrMsg = SetI2CState(False)
    if ErrMsg != '': print('Cannot disable I2C feature:\n'+ErrMsg+'\n')
    time.sleep(1)
  Stat = GetInstStatus()
  if all(value == 0x00 for value in Stat):
    print(CYAN+'Status: '+GREEN+'The script was successfully uninstalled.'+RESET)
    if do_hwfeat: print(YELLOW+'Please reboot your system !'+RESET)
  else: 
    print(CYAN+'Status: '+RED+'The script is not fully uninstalled.'+RESET)
    print(YELLOW+'Something went wrong. The script could not be uninstalled properly.'+RESET)
  print('')
  ShowStatus(Stat)


#----- Clock functions ----------------------------

def UpdatePicoRTC():
  try:
    CDT = datetime.now()
    packedDT = struct.pack('<HBBBBBBB', CDT.year, CDT.month, CDT.day, CDT.weekday(), CDT.hour, CDT.minute, CDT.second, 0)
    with i2cLock: I2CBus.write_i2c_block_data(PicoAddr, regRTC, list(packedDT))
    return True
  except: return False

def ClockSynced():
  try:
    result = subprocess.run(['timedatectl', 'status'], capture_output=True, text=True, check=True)
    lines = result.stdout.splitlines()
    for i in range(len(lines)):
      if ('synchronized' in lines[i]):
        return ('yes' in lines[i])
    return False
  except: return False

def GetSoundEn():
  if not SilentMode or not PiSynced: return True
  CT = datetime.now()
  currTime  = (CT.hour * 60) + CT.minute
  startTime = (SilentSTH * 60) + SilentSTM
  stopTime  = (SilentSPH * 60) + SilentSPM
  if startTime < stopTime:
    Enabled = (currTime < startTime) or (currTime > stopTime)
  else:
    Enabled = (currTime < startTime) and (currTime > stopTime)
  return Enabled


#----- I2C bulk transfer ----------------------------

def ValidCRC(data):
  size = len(data)
  if size < 2: return False
  CRC = 0
  table = crc8_tab
  for i in range(size-1): CRC = table[CRC ^ data[i]]
  return CRC == data[size-1]

def ReadI2CBuff(cmd, buff):
  try:
    bPos = 0; errors = 0; rts = 0; Sig = sigRetry
    bufs = len(buff) // 31; lbs = len(buff) % 31
    if lbs == 0: lbs = 31
    else: bufs += 1
    lbs += 1 # the CRC
    I2CBus.write_i2c_block_data(0x41, regCMD, list(cmd))
    while bufs > 0:
      size = lbs if bufs == 1 else 32
      blk = bytes(I2CBus.read_i2c_block_data(0x41, Sig, size))
      if ValidCRC(blk):
        buff[bPos:bPos+(size-1)] = blk[:-1]
        bPos += 31; bufs -= 1; rts = 0; Sig = sigContinue
      else:
        Sig = sigRetry; errors += 1; rts += 1
        if rts == 10: break
    I2CBus.write_byte(0x41, sigStop)
    if rts == 0: return errors
  except: pass


#----- Mount / Unmount -------------------------

def NasSysDir(path):
  if not os.path.isdir(path):
    try: os.mkdir(path)
    except Exception as E: return f'Mkdir [{path}] Error: {E}'
  try: os.chmod(path, NasPerms)
  except Exception as E: return f'Chmod [{path}] Error: {E}'
  try: shutil.chown(path, 'root', NasGroup)
  except Exception as E: return f'Chown [{path}] Error: {E}'
  return ''

def CheckMount(mpoint):
  try:
    nas_stat = os.stat(NasRoot)
    if not os.path.exists(mpoint): return ''
    mpt_stat = os.stat(mpoint)
    if nas_stat.st_dev == mpt_stat.st_dev: return ''
    else: return f'Warning: it seems that {mpoint} is still mounted.'
  except Exception as E:
    return f'CheckMount Error: {E}'

def RemoveUnmounted():
  try:
    MountPoints = [os.path.join(NasRoot, folder) for folder in os.listdir(NasRoot) if os.path.isdir(os.path.join(NasRoot, folder))]
    nas_stat = os.stat(NasRoot)
    for I in range(len(MountPoints)-1, -1, -1):
      mpt_stat = os.stat(MountPoints[I])
      if nas_stat.st_dev == mpt_stat.st_dev:
        try: os.rmdir(MountPoints[I])
        except: pass
      else: del MountPoints[I]
    ChangeFileLines('/etc/fstab', [], MountPoints)
  except: pass


#----- Network functions -------------------------------

def MakeCMD(CmdCode):
  bin = bytearray(CmdCode)
  bin[1] = RASPI_CMDID
  return bytes(bin)

def CompCMD(CmdCode, TestCode):
  bin = bytearray(CmdCode)
  TheID = bin[1]; bin[1] = 0x00
  CmdCode = bytes(bin)
  return (TheID == COMP_CMDID) and (CmdCode == TestCode)

def FromComp(CmdCode):
  bin = bytearray(CmdCode)
  return (bin[1] == COMP_CMDID)

def FromAndro(CmdCode):
  bin = bytearray(CmdCode)
  return (bin[1] == ANDRO_CMDID)

def GetCMD(CmdCode):
  bin = bytearray(CmdCode)
  bin[1] = 0x00
  return bytes(bin)


def ValidCompAddr():
  try:
    with cfgLock:
      CompIP   = Config['Network']['CompIP']
      CompPort = int(Config['Network']['CompPort'])
      isValid  = (CompIP != 'none') and (CompPort > 0) and (CompPort <= 65535)
      return (CompIP, CompPort) if isValid else None
  except: return None    

def ValidRaspiAddr():
  try:
    with cfgLock:
      RaspiIP   = Config['Network']['RaspiIP']
      RaspiPort = int(Config['Network']['RaspiPort'])
      isValid   = (RaspiPort > 0) and (RaspiPort <= 65535)
      return (RaspiIP, RaspiPort) if isValid else None
  except: return None    

def SendBuff(Cmd, Buff, AddSize = True, Validate = False):
  try:
    CompAddr = ValidCompAddr()
    if CompAddr == None: return False
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as CSocket:
      BuffSize = struct.pack('<I', len(Buff))
      CSocket.settimeout(1)
      CSocket.connect(CompAddr)
      if AddSize: CSocket.sendall(MakeCMD(Cmd) + BuffSize + Buff)
      else: CSocket.sendall(MakeCMD(Cmd) + Buff)
      return not Validate or (CSocket.recv(4) == CMD_SUCCESS)
  except Exception as E:
    if Debug: print(f' SendBuff error: {E}')
    return False

def SendRaspiReady():
  try:
    CompAddr = ValidCompAddr()
    if CompAddr == None: return
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as CSocket:
      CSocket.settimeout(1)
      CSocket.connect(CompAddr)
      CSocket.sendall(MakeCMD(CMD_RPIREADY))
  except Exception as E:
    if Debug: print(f' SendRaspiReady error: {E}')

def SendBackOnline():
  global REG_Shutdown, REG_Power, REG_Battery, REG_BatOver
  try:
    with i2cLock: SBuff = I2CBus.read_i2c_block_data(PicoAddr, regAlert, 16)
    SRegShd = bytes(SBuff[:4]);   REG_Shutdown = SRegShd
    SRegPwr = bytes(SBuff[4:8]);  REG_Power = SRegPwr
    SRegBat = bytes(SBuff[8:12]); REG_Battery = SRegBat
    SRegOvr = bytes(SBuff[12:]);  REG_BatOver = SRegOvr
    StatType = 1 if (SRegPwr == stPowerON) and (SRegBat == stBatON) and (SRegShd != stShdLow) else 2
    if SRegOvr == stBatOver: StatType = 3
    if SRegPwr == stPowerON: MainStat = 'ON'
    elif SRegPwr == stPowerOFF: MainStat = 'OFF'
    else: MainStat = 'UNK'
    if SRegOvr == stBatOver: BatStat = 'OVR'
    elif SRegBat == stBatOFF: BatStat = 'OFF'
    elif SRegShd == stShdLow: BatStat = 'LOW'
    elif SRegBat == stBatON: BatStat = 'ON'
    else: BatStat = 'UNK'
  except:
    StatType = 2; MainStat = 'UNK'; BatStat = 'UNK'
  BroadcastMsg(OnlineMsg, StatType, [MainStat, BatStat])

def Connectable(Addr):
  try:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as CSocket:
      CSocket.settimeout(0.1)
      CSocket.connect(Addr)
    return True
  except: return False


def GetIPAddress(ifname):
  try:
    SIOCGIFADDR = 0x8915
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
      packed_name = struct.pack('256s', ifname[:15].encode('utf-8'))
      bin_address = fcntl.ioctl(sock.fileno(), SIOCGIFADDR, packed_name)
      ip_address = socket.inet_ntoa(bin_address[20:24])
    return ip_address
  except: return None

def GetAdapterList():
  List = []
  adapters = netifaces.interfaces()
  for adapter in adapters:
    ip_addr = GetIPAddress(adapter)
    if (ip_addr != None) and (ip_addr != '127.0.0.1'):
      List.append([adapter, ip_addr])
  return List

def IPExists(ip_test):
  adapters = netifaces.interfaces()
  for adapter in adapters:
    ip_addr = GetIPAddress(adapter)
    if (ip_addr != None) and (ip_addr != '127.0.0.1'):
      if ip_addr == ip_test: return True
  else: return False

def ValidForServer(host, port):
  with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as Test:
    try:
      Test.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
      Test.bind((host, port))
      return True
    except:
      return False

def GetServerAddr():
  AdpList = GetAdapterList()
  if len(AdpList) == 0: return 'This system has no network adapter'
  SrvAddr = ValidRaspiAddr()
  if SrvAddr == None: return 'Invalid server address'
  if (SrvAddr[0] == 'none') or (not any(adp[1] == SrvAddr[0] for adp in AdpList)):  
    SrvAddr = (AdpList[0][1], SrvAddr[1])
  return f'Server addres is: {SrvAddr[0]}:{SrvAddr[1]}'


#----- Temperature & Fan --------------------------------

def AddDataValues(DataBuff, Val1, Val2):
  V1data = struct.pack('<H', Val1)
  V2data = struct.pack('<H', Val2)
  Vidx = struct.unpack('<H', DataBuff[DPosI:])[0]
  DataBuff[DPos1+Vidx] = V1data[0]
  DataBuff[DPos2+Vidx] = V2data[0]
  Vidx += 1
  DataBuff[DPos1+Vidx] = V1data[1]
  DataBuff[DPos2+Vidx] = V2data[1]
  Vidx += 1
  if Vidx >= DPos2: Vidx = 0
  DataBuff[DPosI:] = struct.pack('<H', Vidx)

def SaveTermGraph():
  DT = datetime.now()
  TimeBuff = struct.pack('<HHHHH', DT.year, DT.month, DT.day, DT.hour, DT.minute)
  with open(TermFile, 'wb') as termFile:
    termFile.write(TermBuff)
    termFile.write(TimeBuff)

def SaveGraphs():
  if PiSynced:
    SaveTermGraph()
  else:
    try: os.remove(TermFile)
    except: pass

def RestoreGraphs():
  def RestoreGr(NBuff, FPath):
    try:
      with open(FPath, 'rb') as binFile:
        Line1 = binFile.read(2880)
        Line2 = binFile.read(2880)
        GIdx  = struct.unpack('<H', binFile.read(2))[0]
        GT = struct.unpack('<HHHHH', binFile.read(10))
      NT = datetime.now()
      GTS = time.mktime((GT[0], GT[1], GT[2], GT[3], GT[4], 0, 0, 0, -1))
      NTS = time.mktime((NT.year, NT.month, NT.day, NT.hour, NT.minute, 0, 0, 0, -1))
      MDiff = int(NTS - GTS) // 60; Diff = MDiff * 2
      if (MDiff < 0) or (MDiff >= 1440): return
      NIdx = struct.unpack('<H', NBuff[-2:])[0]
      Line1 = Line1[GIdx:] + Line1[:GIdx]
      Line2 = Line2[GIdx:] + Line2[:GIdx]
      Size = 2880 - Diff
      NBuff[0000+NIdx:0000+NIdx+Size] = Line1[-Size:]
      NBuff[2880+NIdx:2880+NIdx+Size] = Line2[-Size:]
      I = NIdx+Size-2; V1 = NBuff[I:I+2]; V2 = NBuff[2880+I:2880+I+2]; I += 2
      while I < 2880:
        NBuff[0000+I:0000+I+2] = V1
        NBuff[2880+I:2880+I+2] = V2
        I += 2
    except: pass
  global GraphsHandled
  if GraphsHandled or not PiSynced: return
  RestoreGr(TermBuff, TermFile)
  if not Debug:
    try: os.remove(TermFile)
    except: pass
  GraphsHandled = True

def ReadCoreTemp():
  try:
    Temps = psutil.sensors_temperatures()
    Core = Temps['cpu_thermal'][0].current
    return int(Core * 100)
  except: return 0


def GetDutyCycle(Temp):
  if not NasFAuto: return FixDuty
  elif Temp <= LowTemp: return 0
  elif Temp >= HighTemp: return HighDuty
  else: return ((Temp - LowTemp) * DPG) + LowDuty

def FilterDC(Value, Step):
  X = round(Value / Step)
  return X * Step

def ResetRPM():
  global ICount
  global RPM_StartTime
  ICount = 0;
  RPM_StartTime = time.time()

def GetRPM():
  global RPM_StartTime
  global ICount
  NowTime = time.time()
  Count = ICount; ICount = 0
  Duration = NowTime - RPM_StartTime
  RPM_StartTime = NowTime
  Freq = Count / Duration
  return int(Freq * 30)


# ----- Notifications ----------------------------

def BroadcastMsg(MsgCode, LID=1, Params=()):
  try:
    LongMsg = MsgFormat(BrdMsg[MsgCode], Params)
    ShortMsg = LongMsg.split('\n', 1)[0]
    if ShortMsg.endswith(':'): ShortMsg = ShortMsg[:-1] + '.'
    if (LID < 1) or (LID > 3): LID = 1;
    CompNotify, PushNotify, LogNotify, UseIdle, IdleVal = GetNotifParams(MsgCode)
    if not CompNotify: mins = -1
    else: mins = SendMessageToComp(CMD_MESSAGE, LongMsg, LID)
    if PushNotify:
     if not UseIdle or (mins < 0) or (mins >= IdleVal): SendMessageToAndro(ShortMsg, LID)
    if Debug: print(EventColor[LID] + LongMsg + RESET)
    elif LogNotify: SendMessageToLog(LongMsg)
  except Exception as E:
    if Debug: print(f' BroadcastMsg error: {E}')

def GetNotifParams(MsgCode):
  with cfgLock:
    try:
      Notif = Config['Notifications']
      UseIdle = Notif.getboolean('UseIdle')
      IdleVal = Notif.getint('IdleVal')
      if MsgCode == OnlineMsg:    return Notif.getboolean('Online.comp'),    Notif.getboolean('Online.push'),    Notif.getboolean('Online.log'),    UseIdle, IdleVal
      if MsgCode == RebootMsg:    return Notif.getboolean('Reboot.comp'),    Notif.getboolean('Reboot.push'),    Notif.getboolean('Reboot.log'),    UseIdle, IdleVal
      if MsgCode == ShutdownMsg:  return Notif.getboolean('Shutdown.comp'),  Notif.getboolean('Shutdown.push'),  Notif.getboolean('Shutdown.log'),  UseIdle, IdleVal
      if MsgCode == MainLostMsg:  return Notif.getboolean('MainLost.comp'),  Notif.getboolean('MainLost.push'),  Notif.getboolean('MainLost.log'),  UseIdle, IdleVal
      if MsgCode == MainAvailMsg: return Notif.getboolean('MainAvail.comp'), Notif.getboolean('MainAvail.push'), Notif.getboolean('MainAvail.log'), UseIdle, IdleVal
      if MsgCode == BatLowMsg:    return Notif.getboolean('BatLow.comp'),    Notif.getboolean('BatLow.push'),    Notif.getboolean('BatLow.log'),    UseIdle, IdleVal
      if MsgCode == BatSafeMsg:   return Notif.getboolean('BatSafe.comp'),   Notif.getboolean('BatSafe.push'),   Notif.getboolean('BatSafe.log'),   UseIdle, IdleVal
      if MsgCode == BatLostMsg:   return Notif.getboolean('BatLost.comp'),   Notif.getboolean('BatLost.push'),   Notif.getboolean('BatLost.log'),   UseIdle, IdleVal
      if MsgCode == BatAvailMsg:  return Notif.getboolean('BatAvail.comp'),  Notif.getboolean('BatAvail.push'),  Notif.getboolean('BatAvail.log'),  UseIdle, IdleVal
      if MsgCode == BatOvr1Msg:   return Notif.getboolean('BatOvr1.comp'),   Notif.getboolean('BatOvr1.push'),   Notif.getboolean('BatOvr1.log'),   UseIdle, IdleVal
      if MsgCode == BatOvr0Msg:   return Notif.getboolean('BatOvr0.comp'),   Notif.getboolean('BatOvr0.push'),   Notif.getboolean('BatOvr0.log'),   UseIdle, IdleVal
      if MsgCode == AppTermMsg:   return Notif.getboolean('AppTerm.comp'),   Notif.getboolean('AppTerm.push'),   Notif.getboolean('AppTerm.log'),   UseIdle, IdleVal
      if MsgCode == HddPark1Msg:  return Notif.getboolean('HddPark.comp'),   Notif.getboolean('HddPark.push'),   Notif.getboolean('HddPark.log'),   UseIdle, IdleVal
      if MsgCode == HddPark0Msg:  return Notif.getboolean('HddPark.comp'),   Notif.getboolean('HddPark.push'),   Notif.getboolean('HddPark.log'),   UseIdle, IdleVal
    except:
      return False, False, False, False, 0

# return: -1 if failed, idle minutes if success
def SendMessageToComp(Cmd, Msg, LID):
  try:
    CompAddr = ValidCompAddr()
    if CompAddr == None: return -1
    MsgBody = Msg.encode('utf-8')
    MsgSize = struct.pack('<I', len(MsgBody))
    MsgType = struct.pack('<B', LID)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as CSocket:
      CSocket.settimeout(1)
      CSocket.connect(CompAddr)
      CSocket.sendall(MakeCMD(Cmd) + MsgType + MsgSize + MsgBody)
      Buff = CSocket.recv(4)
    if len(Buff) != 4: Idle = -1
    else: Idle = struct.unpack('<I', Buff)[0]
    return Idle
  except Exception as E:
    if Debug: print(f' SendMessageToComp error: {E}')
    return -1

def SendMessageToAndro(Msg, LID):
  global AndroMsgPool, AMPModified
  MsgLevel = ['default', 'normal', 'warning', 'critical']
  if (LID < 1) or (LID > 3): LID = 1;
  try:
    now_ts = datetime.now().timestamp()
    with ampLock:
      AndroMsgPool += PackMessage(now_ts, LID, Msg)  
      AMPModified = True 
    btime = struct.pack('>d', now_ts)  
    TimeEnc = btime.hex().upper()
    with cfgLock:
      AppToken = Config['Firebase']['AppToken']
      FCMLink  = Config['Firebase']['FCMLink']
    if (AppToken == '') or (AppToken == 'none') or (FCMLink == '') or (FCMLink == 'none'): return False
    Headers = { 'Content-Type': 'application/json' }
    Payload = {
      'app_token': AppToken,
      'msg_title': 'Raspberry Pi NAS',
      'msg_body' : Msg,
      'msg_level': MsgLevel[LID],
      'msg_time' : TimeEnc }
    Response = requests.post(FCMLink, headers=Headers, json=Payload)
    return (Response.status_code == 200)
  except Exception as E:
    if Debug: print(f' SendMessageToAndro error: {E}')
    return False  

def SendMessageToLog(Msg):
  if not Debug:
    try:
      with logLock:
        with open(LogEventsFile, 'a', encoding='utf-8') as log:
          log.write(datetime.now().strftime('[%Y-%m-%d, %H:%M:%S] : ')+Msg+'\n')
    except: pass

def SaveAndroMsgPool():
  global AMPModified
  try:
    with ampLock:
      if AMPModified:
        with open(AMPFile, 'wb') as ampFile:
          ampFile.write(AndroMsgPool)
          ampFile.flush()
          os.fsync(ampFile.fileno())
        AMPModified = False
  except: pass

# --- Configuration --------------------------

def SaveConfig():
  global SaveCfgTimer
  with cfgLock:
    if SaveCfgTimer != None: SaveCfgTimer.cancel()
    SaveCfgTimer = threading.Timer(600, SaveConfigNow);
    SaveCfgTimer.start()

def SaveConfigNow(forced=False):
  global SaveCfgTimer
  try:
    with cfgLock:
      if forced or (SaveCfgTimer != None):
        with open(CustomSettingsFile, 'w') as cs: Config.write(cs)
        if SaveCfgTimer != None:
          SaveCfgTimer.cancel()
          SaveCfgTimer = None
  except Exception as E:
    if Debug: print(f' SaveConfigNow error: {E}')

     #--- Network -------

def SetNetworkCfg(CIP, CPort, RIP, RPort):
  try:
    if not IPExists(RIP):
      if Debug: print(f'The IP {RIP} does not exists on this system.')
      return False
    with cfgLock:
      Config['Network']['CompIP']    = CIP
      Config['Network']['CompPort']  = CPort
      Config['Network']['RaspiIP']   = RIP
      Config['Network']['RaspiPort'] = RPort
      SaveConfig()
    return True
  except Exception as E:
    if Debug: print(RED+f' SetNetworkCfg error: {E}'+RESET)
    return False

     #--- Standby -------

def PackStandbyCfg():
  def GetDiskParams(Data):
    Vals = Data.split('/')
    return int(Vals[0]), int(Vals[1])
  try:
    with cfgLock:
      Standby = Config['Standby']
      GenEn = Standby.getboolean('Enabled')
      ChkPer = Standby.getint('CheckPeriod')
      DefKA, DefSB = GetDiskParams(Standby['Default'])
      StbCustom = Config['StandbyCustom']
      DCount = len(StbCustom)
      StbPack = struct.pack('<?IIII', GenEn, ChkPer, DefKA, DefSB, DCount)
      for Serial in StbCustom:
        ValKA, ValSB = GetDiskParams(StbCustom[Serial])
        StbPack += PackSStr(Serial) + struct.pack('<II', ValKA, ValSB)
    return StbPack
  except Exception as E:
    if Debug: print(RED+f' PackStandbyCfg error: {E}'+RESET)
    return b''

def SetStbConfig(Buff):
  try:
    with cfgLock:
      if PackStandbyCfg() != Buff:
        Standby = Config['Standby']; I = 0
        GenEn, ChkPer, DefKA, DefSB, DCount = struct.unpack('<?IIII', Buff[I:I+17]); I += 17
        Standby['Enabled'] = 'yes' if GenEn else 'no'
        Standby['CheckPeriod'] = str(ChkPer)
        Standby['Default'] = str(DefKA) + '/' + str(DefSB)
        DList = Config.options('StandbyCustom')
        StbCustom = Config['StandbyCustom']
        for disk in DList: del StbCustom[disk]
        for x in range(DCount):
          Serial, Size = UnpackSStr(Buff, I); I += Size
          DiskKA, DiskSB = struct.unpack('<II', Buff[I:I+8]); I += 8
          StbCustom[Serial] = str(DiskKA) + '/' + str(DiskSB)
        SaveConfig()
        with devLock:
          SetCheckPeriod(ChkPer)
          UpdateBlockDevices()
          if Debug: ShowStatInfo()
        if Debug: print(' Standby settings updated')
      else:
        if Debug: print(' Received the same Standby settings')
    return True
  except Exception as E:
    if Debug: print(RED+f' SetStbConfig error: {E}'+RESET)
    return False

def SetCheckPeriod(Value):
  global CheckPeriod
  with clkLock:
    with devLock:
      for dev in DevList:
        AliveTime = dev[5][1] * CheckPeriod
        dev[5][1] = AliveTime // Value
        IdleTime  = dev[5][2] * CheckPeriod
        dev[5][2] = IdleTime // Value
      CheckPeriod = Value
      if Debug: print(f'\nCheck Period = {CheckPeriod} seconds\n')

     #--- A.P.M. ---------

def PackApmCfg():
  try:
    with cfgLock:
      Apm = Config['APM']
      GenEn = Apm.getboolean('Enabled')
      DefApm = Apm.getint('Default')
      DefEn = DefApm != 0
      ApmCustom = Config['ApmCustom']
      DCount = len(ApmCustom)
      ApmPack = struct.pack('<??BI', GenEn, DefEn, DefApm, DCount)
      for Serial in ApmCustom:
        DiskApm = ApmCustom.getint(Serial)
        ApmPack += PackSStr(Serial) + struct.pack('<B', DiskApm)
    return ApmPack
  except Exception as E:
    if Debug: print(RED+f' PackApmCfg error: {E}'+RESET)
    return b''

def SetApmConfig(Buff):
  try:
    with cfgLock:
      if PackApmCfg() != Buff:
        Apm = Config['APM']; I = 0
        GenEn, DefEn, DefApm, DCount = struct.unpack('<??BI', Buff[I:I+7]); I += 7
        Apm['Enabled'] = 'yes' if GenEn else 'no'
        if not DefEn: Apm['Default'] = '0'
        else: Apm['Default'] = str(DefApm)
        DList = Config.options('ApmCustom')
        ApmCustom = Config['ApmCustom']
        for disk in DList: del ApmCustom[disk]
        for x in range(DCount):
          Serial, Size = UnpackSStr(Buff, I); I += Size
          DiskApm = struct.unpack('<B', Buff[I:I+1])[0]; I += 1
          ApmCustom[Serial] = str(DiskApm)
        SaveConfig()
        with devLock:
          for disk in DevList:
            if disk[5][3] == 1: SetTargetAPM(disk)
        if Debug: print(' APM settings updated')
      else:
        if Debug: print(' Received the same APM settings')
    return True
  except Exception as E:
    if Debug: print(RED+f' SetApmConfig error: {E}'+RESET)
    return False

     #--- Firebase -------

def SetAppTokenCfg(token):
  try:
    if token == '': token = 'none'
    with cfgLock:
      Firebase = Config['Firebase']
      if Firebase['AppToken'] != token:
        Firebase['AppToken'] = token
        SaveConfig()
        if Debug: print(' AppToken updated')
      else:
        if Debug: print(' Received the same AppToken')  
    return True
  except Exception as E:
    if Debug: print(RED+f' AppTokenConfig error: {E}'+RESET)
    return False
    
def SetFCMLinkCfg(link):
  try:
    if link == '': link = 'none'
    with cfgLock:
      Firebase = Config['Firebase']
      if Firebase['FCMLink'] != link:
        Firebase['FCMLink'] = link
        SaveConfig()
        if Debug: print(' FCM Link updated')
      else:
        if Debug: print(' Received the same FCM Link')  
    return True
  except Exception as E:
    if Debug: print(RED+f' FCMLinkConfig error: {E}'+RESET)
    return False

     #--- Notifs -------

def PackNotifCfg():
  try:
    Notifs = bytearray(13*3);
    with cfgLock:
      GNotif = Config['Notifications']
      x = 0
      for N in range(13):
        for e in range(3):
          Notifs[x] = int(GNotif.getboolean(NotifName[N]+NotifExt[e]))
          x += 1
      UseI = GNotif.getboolean('UseIdle')
      Idle = GNotif.getint('IdleVal')
    return bytes(Notifs) + struct.pack('<?H', UseI, Idle)
  except: return b''

def SetNotifConfig(Buff):
  try:
    with cfgLock:
      if PackNotifCfg() != Buff:
        GNotif = Config['Notifications']
        I = 0
        for N in range(13):
          for e in range(3):
            value = 'no' if int(Buff[I]) == 0 else 'yes'
            GNotif[NotifName[N]+NotifExt[e]] = value
            I += 1
        UseI = 'yes' if struct.unpack('<?', Buff[I:I+1])[0] else 'no';  I += 1
        Idle = str(struct.unpack('<H', Buff[I:I+2])[0])
        GNotif['UseIdle'] = UseI
        GNotif['IdleVal'] = Idle
        SaveConfig()
        if Debug: print(' Notif settings updated')
      else:
        if Debug: print(' Received the same Notif settings')
    return True
  except Exception as E:
    if Debug: print(RED+f' NotifConfig error: {E}'+RESET)
    return False

     #--- NAS Fan -------

def ReadNasFanParams():
  global NasFAuto, LowTemp, HighTemp, LowDuty, HighDuty, FixDuty, DPG
  with cfgLock:
    try:
      GFan = Config['Cooling']
      NasFAuto = GFan.getboolean('NasFAuto')
      LowTemp  = GFan.getint('NasLowTemp')
      HighTemp = GFan.getint('NasHighTemp')
      LowDuty  = GFan.getint('NasLowDuty')
      HighDuty = GFan.getint('NasHighDuty')
      FixDuty  = GFan.getint('NasFixDuty')
      DPG = (HighDuty - LowDuty) / (HighTemp - LowTemp)
      return True
    except: return False

def PackNasFanCfg():
  try:
    with cfgLock:
      GFan = Config['Cooling']
      LNasFAuto = GFan.getboolean('NasFAuto')
      LLowTemp  = GFan.getint('NasLowTemp')
      LHighTemp = GFan.getint('NasHighTemp')
      LLowDuty  = GFan.getint('NasLowDuty')
      LHighDuty = GFan.getint('NasHighDuty')
      LFixDuty  = GFan.getint('NasFixDuty')
  except: return b''
  return struct.pack('<?HHHHH', LNasFAuto, LLowTemp, LHighTemp, LLowDuty, LHighDuty, LFixDuty)

def SetNasFanConfig(Buff):
  global NasFAuto, LowTemp, HighTemp, LowDuty, HighDuty, FixDuty, DPG
  try:
    with cfgLock:
      if PackNasFanCfg() != Buff:
        NasFAuto, LowTemp, HighTemp, LowDuty, HighDuty, FixDuty = struct.unpack('<?HHHHH', Buff)
        Cooling = Config['Cooling']
        Cooling['NasFAuto']    = 'yes' if NasFAuto else 'no'
        Cooling['NasLowTemp']  = str(LowTemp)
        Cooling['NasHighTemp'] = str(HighTemp)
        Cooling['NasLowDuty']  = str(LowDuty)
        Cooling['NasHighDuty'] = str(HighDuty)
        Cooling['NasFixDuty']  = str(FixDuty)
        DPG = (HighDuty - LowDuty) / (HighTemp - LowTemp)
        SaveConfig()
        if Debug: print(' NAS Fan settings updated')
      else:
        if Debug: print(' Received the same NAS Fan settings')
    return True
  except Exception as E:
    if Debug: print(RED+f' NasFanConfig error: {E}'+RESET)
    return False

     #--- Silent Mode -------

def ReadSilentParams():
  global SilentMode, SilentSTH, SilentSTM, SilentSPH, SilentSPM, MaxFDuty
  with cfgLock:
    try:
      GSil = Config['Silent']
      SilentMode = GSil.getboolean('Enabled')
      SilentSTH  = GSil.getint('StartHour')
      SilentSTM  = GSil.getint('StartMin')
      SilentSPH  = GSil.getint('StopHour')
      SilentSPM  = GSil.getint('StopMin')
      MaxFDuty   = GSil.getint('MaxFDuty')
      return True
    except: return False

def PackSilentCfg():
  try:
    with cfgLock:
      GSil = Config['Silent']
      LSilMode = GSil.getboolean('Enabled')
      LSilSTH  = GSil.getint('StartHour')
      LSilSTM  = GSil.getint('StartMin')
      LSilSPH  = GSil.getint('StopHour')
      LSilSPM  = GSil.getint('StopMin')
      LMaxDuty = GSil.getint('MaxFDuty')
  except: return b''
  return struct.pack('<?HHHHH', LSilMode, LSilSTH, LSilSTM, LSilSPH, LSilSPM, LMaxDuty)

def SetSilentConfig(Buff):
  global SilentMode, SilentSTH, SilentSTM, SilentSPH, SilentSPM, MaxFDuty, SoundEn, FanDuty
  try:
    with cfgLock:
      if PackSilentCfg() != Buff:
        SilentMode, SilentSTH, SilentSTM, SilentSPH, SilentSPM, MaxFDuty = struct.unpack('<?HHHHH', Buff)
        Silent = Config['Silent']
        Silent['Enabled']   = 'yes' if SilentMode else 'no'
        Silent['StartHour'] = str(SilentSTH)
        Silent['StartMin']  = str(SilentSTM)
        Silent['StopHour']  = str(SilentSPH)
        Silent['StopMin']   = str(SilentSPM)
        Silent['MaxFDuty']  = str(MaxFDuty)
        SaveConfig()
        if Debug: print(' Silent Mode settings updated')
        SoundEn = GetSoundEn()
        if not SoundEn and FanDuty > MaxFDuty:
          FanDuty = MaxFDuty
          FanPWM.SetDuty(FanDuty)
      else:
        if Debug: print(' Received the same Silent Mode settings')
    return True
  except Exception as E:
    if Debug: print(RED+f' SilentConfig error: {E}'+RESET)
    return False


# ----- Devices section ----------------------------

def UpdateBlockDevices():
  global StartInStandby
  UpdateMountPoints(); UpdateCounters(); NewDisks = []
  for dev in UDEV.list_devices(subsystem='block', DEVTYPE='disk'):
    if re.match(r'sd[a-z]$', dev.sys_name):
      NewDisks.append(dev.sys_name)
      Idx = GetDiskIndex(dev.device_node)
      if not ('ID_SERIAL_SHORT' in dev.properties): dev_serial = ''
      else: dev_serial = dev.properties['ID_SERIAL_SHORT']
      dev_size = GetFileSize(dev.device_node)
      dev_rot = RotationalDisk(dev.sys_name)
      dev_parts = GetPartition(dev)
      apm_avail = ApmAvailable(dev_serial, False)  
      KAS, SBT = GetDevStandbyParams(dev_serial)
      IsKnown = (KAS > 0) or (SBT > 0); do_apm = False  
      if Idx != None:  # already exists
        dev_stat = DevList[Idx][5]
        WasKnown = (dev_stat[5] > 0) or (dev_stat[6] > 0)
        dev_stat[5] = KAS; dev_stat[6] = SBT
        if WasKnown and not IsKnown:
          dev_stat[3] = 0; dev_stat[4] = 'unknown'
        if not WasKnown and IsKnown:
          do_apm = True  
          dev_stat[3] = 1; dev_stat[4] = 'active'
          dev_stat[0] = GetDiskCount(dev.sys_name) + KeepAliveAsync(dev.device_node)
          dev_stat[1] = 0; dev_stat[2] = 0
          if apm_avail == 0: apm_avail = ApmAvailable(dev_serial)
        DevList[Idx] = [dev.sys_name, dev.device_node, dev_serial, dev_size, dev_rot, dev_stat, dev_parts, apm_avail]
        if do_apm: SetTargetAPM(DevList[Idx])
      else:            # new drive
        if dev_rot != 2:
          dev_stat = [0, 0, 0, 0, 'unknown']
        else:
          new_count = GetDiskCount(dev.sys_name)
          if not IsKnown:
            ST_Code = 0; ST_Name = 'unknown'
          else:
            if StartInStandby:
              ST_Code = 2; ST_Name = 'standby'
            else:
              do_apm = True  
              ST_Code = 1; ST_Name = 'active'
              new_count += KeepAlive(dev.device_node)
              if apm_avail == 0: apm_avail = ApmAvailable(dev_serial)
          dev_stat = [new_count, 0, 0, ST_Code, ST_Name, KAS, SBT]
        DevList.append([dev.sys_name, dev.device_node, dev_serial, dev_size, dev_rot, dev_stat, dev_parts, apm_avail])
        if do_apm: SetTargetAPM(DevList[-1])
  for old_disk in DevList:
    for new_disk in NewDisks:
      if old_disk[0] == new_disk: break
    else: DevList.remove(old_disk)
  if len(DevList) > 0: DevList.sort(key=lambda x: x[0])
  StartInStandby = False

def PackBlockDevices():
  buff = struct.pack('<H', len(DevList))
  for disk in DevList:
    buff += PackWStr(disk[0]) + PackWStr(disk[1]) + PackWStr(disk[2])
    buff += struct.pack('<QBBQIIB', disk[3], disk[4], disk[7], disk[5][0], disk[5][1], disk[5][2], disk[5][3])
    buff += PackWStr(disk[5][4]) + struct.pack('<H', len(disk[6]))
    for part in disk[6]:
      for i in range(5): buff += PackWStr(part[i])
      buff += struct.pack('<QH', part[5], len(part[6]))
      for mp in part[6]: buff += PackWStr(mp)
  return buff

def DevNode(Serial): 
  with devLock:
    for dev in DevList:
      if dev[2] == Serial: return dev[1]
    else: return ''
    
def DevSerial(dev_node): 
  with devLock:
    for dev in DevList:
      if dev[1] == dev_node: return dev[2]
    else: return ''

def GetDevStandbyParams(Serial):
  KAS = 0; SBT = 0;
  try:
    with cfgLock:
      Standby = Config['Standby']
      if Standby.getboolean('Enabled'):
        StbCustom = Config['StandbyCustom']
        for DiskSer in StbCustom:
          if DiskSer == Serial:
            Data = StbCustom[DiskSer].split('/')
            break
        else: Data = Standby['Default'].split('/')
        KAS = int(Data[0]); SBT = int(Data[1])
  except: pass
  return KAS, SBT

def GetFileSize(filename):
  fd = os.open(filename, os.O_RDONLY)
  try:
    size = os.lseek(fd, 0, os.SEEK_END)
  except:
    size = 0
    if Debug: print(f' GetFileSize error: Cannot get size of "{filename}".')
  os.close(fd)
  return size

def UpdateCounters():
  global Counters
  Counters = psutil.disk_io_counters(perdisk=True)

def GetDiskCount(disk_name):  # update counters first
  for disk in Counters:
    if disk == disk_name:
      return Counters[disk].read_count + Counters[disk].write_count
  else: return 0

def UpdateMountPoints():
  global MountPoints
  MountPoints = psutil.disk_partitions()

def GetMountPoint(dev_node):  # update mount points first
  for mp in MountPoints:
    if mp.device == dev_node:
      if mp.mountpoint == '/': mnt_dir = mp.mountpoint
      else: mnt_dir = mp.mountpoint.rsplit('/',1)[-1]
      return [mnt_dir, mp.mountpoint, mp.fstype, mp.opts]
  else: return []

def GetPartition(disk_dev):   # update mount points first
  parts = []
  for part in disk_dev.children:
    part_lab  = part.get('ID_FS_LABEL'); part_lab  = '' if part_lab is None else part_lab
    part_uuid = part.get('ID_FS_UUID');  part_uuid = '' if part_uuid is None else part_uuid
    part_fst  = part.get('ID_FS_TYPE');  part_fst  = '' if part_fst is None else part_fst
    part_size = GetFileSize(part.device_node)
    part_mount = GetMountPoint(part.device_node)
    parts.append((part.sys_name, part.device_node, part_lab, part_uuid, part_fst, part_size, part_mount))
  return parts

def RotationalDisk(disk_name):
  rot_file = '/sys/block/{}/queue/rotational'.format(disk_name)
  try:
    with open(rot_file, 'r') as f:
     return int(f.read().strip()) + 1
  except: return 0

def GetDiskIndex(dev_node):
  for D in range(len(DevList)):
    if DevList[D][1] == dev_node: return D
  else: return None

def GetPartIndex(part_node):
  for D in range(len(DevList)):
    for P in range(len(DevList[D][6])):
      if DevList[D][6][P][1] == part_node: return D, P
  else: return None, None

def PartMountInfo(part_node):
  uuid = None; fstype = None; mpoint = None
  D, P = GetPartIndex(part_node)
  if P != None:
    uuid   = DevList[D][6][P][3]
    fstype = DevList[D][6][P][4]
    mpoint = DevList[D][6][P][6]
  return uuid, fstype, mpoint


def SwitchToActive(dev_node):
  try:  
    with devLock:
      Idx = GetDiskIndex(dev_node)
      if (Idx == None) or (DevList[Idx][4] != 2): return    # exit if no device or no HDD
      KeepAlive(dev_node)                                   # access the drive to wake
      if DevList[Idx][7] == 0:
        DevList[Idx][7] = ApmAvailable(DevList[Idx][2])     # update APM Avail
      SetTargetAPM(DevList[Idx])                            # update APM  
      UpdateCounters()  
      DStat = DevList[Idx][5]
      DStat[0] = GetDiskCount(DevList[Idx][0])              # update IO count      
      DStat[1] = 0; DStat[2] = 0                            # reset KA and Idle counters
      DStat[3] = 1; DStat[4] = 'active'                     # mark it as active
      SendBuff(CMD_DEVICES, PackBlockDevices())             # send new status
  except Exception as E:
    if Debug: print(RED+f'SwitchToActive error: {E}'+RESET)

def SwitchToStandby(dev_node):
  try:  
    with devLock:
      Idx = GetDiskIndex(dev_node)
      if (Idx == None) or (DevList[Idx][4] != 2): return    # exit if no device or no HDD
      PutInStandby(dev_node)                                # put the drive in standby
      UpdateCounters()  
      DStat = DevList[Idx][5]
      DStat[0] = GetDiskCount(DevList[Idx][0])              # update IO count      
      DStat[1] = 0                                          # reset KA
      DStat[3] = 2; DStat[4] = 'standby'                    # mark it as inactive
      SendBuff(CMD_DEVICES, PackBlockDevices())             # send new status
  except Exception as E:
    if Debug: print(RED+f'SwitchToStandby error: {E}'+RESET)

def UpdatePowerStatus(dev_node, send=True):
  try:
    time.sleep(0.2)  
    isAct = IsDriveActive(dev_node)
    if isAct == None: return False
    with devLock:
      Idx = GetDiskIndex(dev_node)
      if (Idx == None) or (DevList[Idx][4] != 2): return False  # exit if no device or no HDD
      DStat = DevList[Idx][5];
      if DStat[3] == 0: return False                            # exit if status unknown
      wasAct = DStat[3] != 2;
      if wasAct == isAct: return False                          # exit if status unchanged 
      UpdateCounters()  
      DStat[0] = GetDiskCount(DevList[Idx][0])              # update IO count      
      if isAct: # drive has become active
        DStat[1] = 0; DStat[2] = 0                          # reset KA and Idle counters
        DStat[3] = 1; DStat[4] = 'active'                   # mark it as active
        if DevList[Idx][7] == 0:
          DevList[Idx][7] = ApmAvailable(DevList[Idx][2])   # update APM Avail
        SetTargetAPM(DevList[Idx])                          # update APM  
      else:     # drive has become inactive
        DStat[1] = 0                                        # reset KA
        DStat[3] = 2; DStat[4] = 'standby'                  # mark it as inactive
      if send: SendBuff(CMD_DEVICES, PackBlockDevices())    # send new status
      return not send
  except Exception as E:
    if Debug: print(RED+f'UpdatePowerStatus error: {E}'+RESET)
    return False

def PutInStandby(dev_node):
  try:
    result = subprocess.run(['/usr/sbin/hdparm', '-y', dev_node], capture_output=(not Debug))
    return result.returncode == 0
  except: return False

def IsDriveActive(dev_node):
  try:
    result = subprocess.run(['/usr/sbin/smartctl', '-n', 'standby', dev_node], capture_output=True, text=True)  
    return not ('STANDBY mode' in result.stdout)
  except Exception as E:
    if Debug:
      print('\n' + RED + 'IsDriveActive exception:' + RESET)
      traceback.print_exception(type(E), E, E.__traceback__)

def KeepAlive(dev_node):
  disk_fd = None; fm = None; fl = None; result = 0
  try:
    try:
      disk_fd = os.open(dev_node, os.O_RDONLY | os.O_DIRECT)
      disk_size = os.lseek(disk_fd, 0, os.SEEK_END)
      read_pos = int(disk_size * 0.9) // 4096 * 4096
      os.lseek(disk_fd, read_pos, os.SEEK_SET);
      fl = os.fdopen(disk_fd, 'rb', 0)
      fm = mmap.mmap(-1, 4096)
      fl.readinto(fm)
      result = 1
    finally:
      if fm != None: fm.close()
      if fl != None:
        fl.close()
      else:
        if disk_fd != None: os.close(disk_fd)
  except Exception as E:
    if Debug: print(f' KeepAlive error: {E}')
  return result

def KeepAliveAsync(dev_node):
  threading.Thread(target=KeepAlive, args=(dev_node,), name='Async KeepAlive').start()
  return 1


# ----- Devices: SMART and APM -----------------------

def GetSMART(dev_node):
  try:
    result = subprocess.run(['/usr/sbin/smartctl', '-A', dev_node], capture_output=True, text=True)
    Lines = result.stdout.splitlines()
    if result.returncode != 0:
      Lines = [line for line in Lines if line.strip()]
      return None, '\n'.join(Lines[2:])
  except Exception as E:
    return None, f'Error running smartctl: {E}'
  try:
    while len(Lines) > 0:
      Stop = Lines[0].startswith('ID#')
      del Lines[0]
      if Stop: break
    Attrs = []
    for line in Lines:
      parts = line.split()
      if len(parts) < 10: continue
      Name = parts[1].replace('_', ' ')
      Name = re.sub(rf'\bCt\b', 'Count', Name)
      Attrs.append([int(parts[0]), Name, int(parts[2], 16), int(parts[3]), int(parts[4]), int(parts[5]), int(parts[9])])
    return Attrs, None  
  except Exception as E:
    return None, f'Error at GetSMART: {E}'

def PackSMART(Attrs):
  try:
    SPack = struct.pack('<B', len(Attrs))
    for attr in Attrs:
      PV = struct.pack('<BBBBBQ', attr[0], attr[2], attr[3], attr[4], attr[5], attr[6])
      SPack = SPack + PV + PackSStr(attr[1]) 
    return SPack, None
  except Exception as E:
    return None, f'Error at PackSMART: {E}'

def GetHealth(dev_node):
  try:
    result = subprocess.run(['/usr/sbin/smartctl', '-H', dev_node], capture_output=True, text=True)
    Lines = result.stdout.splitlines()
    if result.returncode != 0:
      Lines = [line for line in Lines if line.strip()]
      return None, '\n'.join(Lines[2:])
  except Exception as E:
    return None, f'Error running smartctl: {E}'
  try:
    for line in Lines:
      if 'overall-health' in line:
        return line.split(':')[-1].strip(), None
    return 'UNKNOWN', None
  except Exception as E:
    return None, f'Error at GetHealth: {E}'


def GetAPM(dev_node):
  try:
    result = subprocess.run(['/usr/sbin/smartctl', '--get=apm', dev_node], capture_output=True, text=True)
    Lines = result.stdout.splitlines()
    if result.returncode != 0:
      Lines = [line for line in Lines if line.strip()]
      return None, '\n'.join(Lines[2:])
  except Exception as E:
    return None, f'Error running smartctl: {E}'
  try:
    for line in Lines:
      if 'APM' in line:
        pattern = r'is:\s*(\w+)'
        match = re.search(pattern, line)
        if not match: break
        elif match.group(1).lower().strip() == 'disabled': return 0x100, None
        elif match.group(1).lower().strip() == 'unavailable': return 0x200, None
        else: return int(match.group(1)), None
    return None, 'Error at GetAPM: invalid smartctl output'
  except Exception as E:
    return None, f'Error at GetAPM: {E}'

def SetTargetAPM(disk):  # call it under devLock
  try:
    if (disk[4] != 2) or (disk[7] != 2): return None  
    APM = None
    with cfgLock:
      if not Config['APM'].getboolean('Enabled'): return None  
      Serial = disk[2]
      if Serial != '':  
        ApmCustom = Config['ApmCustom']
        if Serial in ApmCustom: APM = ApmCustom.getint(Serial)
      if APM == None:
        ApmDef = Config['APM']
        if 'Default' in ApmDef: APM = ApmDef.getint('Default')
    if (APM == None) or (APM == 0): return None  
    result = subprocess.run(['/usr/sbin/smartctl', '--set=apm,'+str(APM), disk[1]], capture_output=True, text=True)
    if result.returncode == 0:
      if Debug: print(f'APM for {disk[1]} set to: {APM}')  
      return None
    Lines = result.stdout.splitlines()
    Lines = [line for line in Lines if line.strip()]
    return '\n'.join(Lines[2:])
  except Exception as E:
    return f'Error at SetTargetAPM: {E}'

def ApmAvailable(serial, check=True):
  try:
    with cfgLock:
      ApmAvail = Config['ApmAvail']
      if serial in ApmAvail:
        return 2 if ApmAvail.getboolean(serial) else 1
      if not check: return 0
      APM = GetAPM(DevNode(serial))[0]
      if APM == None: return False
      HasAPM = APM != 0x200
      ApmAvail[serial] = 'yes' if HasAPM else 'no'
      SaveConfig()
      return 2 if HasAPM else 1      
  except Exception as E:
    if Debug: print(RED+f' ApmAvailable error: {E}'+RESET)
    return 0


# ========================= T H R E A D S =====================================

# [THREAD]: GPIO callbacks

def CountImpulses(event):
  global ICount
  ICount += 1

def UPSAlert(event):
  with upsLock: UPSEvent.set()

def SDRequest(event):
  try:
    global LastSdReq
    tnow = time.time_ns(); ms_diff = (tnow - LastSdReq) / 1000000; LastSdReq = tnow
    if event.event_type is event.Type.RISING_EDGE: SDRList.append([1, ms_diff])
    elif event.event_type is event.Type.FALLING_EDGE: SDRList.append([0, ms_diff])
  except Exception as E: 
    traceback.print_exception(type(E), E, E.__traceback__)  

# [THREAD]: BlockDev Monitor callback

def OnDevUpdate():
  try:
    with devLock:
      UpdateBlockDevices()
      buff = PackBlockDevices()
      if Debug: ShowStatInfo()
    SendBuff(CMD_DEVICES, buff)
    RemoveUnmounted()
  except: pass

# [THREAD]: TCP Command Server

def StopTCPServer():
  TCPSrvEnd.set()
  with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as ESocket:
    try:
      ESocket.settimeout(0.2)
      ESocket.connect(BindedAddr)
    except: pass
  TCPSrv.join()

def ServerThread(EndFlag): #-----------------------------------------------------------

  def SetLabel(part_node, label):
    try:
      result = subprocess.run(['e2label', part_node, label], capture_output=True, text=True)
      if result.returncode != 0:
        return 3, f'e2label error {result.returncode} > {result.stderr.strip()}'
      else:
        return 1, f'The label of {part_node} was successfully set.'
    except: pass

  def UnmountPart(mpoint):
    warn = ''
    result = subprocess.run(['umount', '-v', mpoint], capture_output=True, text=True)
    if result.returncode != 0:
      return 3, f'Unmount error {result.returncode} > {result.stderr.strip()}'
    err = ChangeFileLines('/etc/fstab', [], [mpoint])
    if err != '': return 2, 'Warning (failed to update /etc/fstab): '+err
    err = CheckMount(mpoint)
    if err != '': return 2, err
    if os.path.exists(mpoint):
      try: os.rmdir(mpoint)
      except Exception as E: warn = f'Warning: Cannot remove mount folder > {E}'
    result = subprocess.run(['systemctl', 'daemon-reload'], capture_output=True, text=True)
    if result.returncode != 0:
      return 3, f'Systemd reload error {result.returncode} > {result.stderr.strip()}'
    if warn != '': return 2, warn
    else: return 1, f'The partition was successfully unmounted: {mpoint}'

  def MountPart(uuid, name, fstype):
    err = NasSysDir(NasRoot)
    if err != '': return 3, err
    mpoint = NasRoot+'/'+name
    err = NasSysDir(mpoint)
    if err != '': return 3, err
    mnt_line = f'UUID={uuid} {mpoint} {fstype} defaults,noatime,nodiratime,nofail,async 0 0'
    err = ChangeFileLines('/etc/fstab', [mnt_line], [mpoint])
    if err != '': return 3, 'Error (failed to update /etc/fstab): '+err
    result = subprocess.run(['mount', '-v', mpoint], capture_output=True, text=True)
    if result.returncode != 0:
      return 3, f'Mount error {result.returncode} > {result.stderr.strip()}'
    result = subprocess.run(['systemctl', 'daemon-reload'], capture_output=True, text=True)
    if result.returncode != 0:
      return 3, f'Systemd reload error {result.returncode} > {result.stderr.strip()}'
    return 1, f'The partition was successfully mounted: {mpoint}'

  def GetDevInfo(dev_node):
    RData = ''
    cmd = ['/usr/sbin/smartctl', '-i', '--get=all', dev_node]
    result = subprocess.run(cmd, capture_output=True, text=True)
    lines = result.stdout.splitlines()
    if result.returncode == 0:
      valid = True
      for i in range(len(lines) - 1, -1, -1):
        if valid:
          if lines[i].startswith('Device is') or lines[i].startswith('Local Time') or (len(lines[i]) == 0):
            del lines[i]
          elif lines[i].startswith('==='):
            valid = False
            del lines[i]
          else: lines[i] = re.sub(r'\s+', ' ', lines[i])
        else: del lines[i]
      RData = '\n'.join(lines)
    else:
      lines = [line for line in lines if line.strip()]
      sctl_err = '\n'.join(lines[2:])
      RData = '\n---SmartCtl Error:\n'+sctl_err
    if len(RData) > 0: RData = RData + '\n'

    cmd = ['/usr/sbin/hdparm', '-I', dev_node]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
      lines = result.stdout.splitlines()
      i1 = None; i2 = None
      for i in range(len(lines)):
        if i1 == None:
          if 'Commands/features' in lines[i]: i1 = i + 2
        else:
          if (len(lines[i]) < 1) or ((i >= i1) and (lines[i][0] != chr(9)) and (lines[i][0] != ' ')):
            i2 = i - 1; break
      else: i2 = i
      if (i1 == None) or (i2 == None): return True, ''
      tmp_line = lines[i1].lstrip('\t *')
      start = len(lines[i1]) - len(tmp_line)
      for i in range(len(lines)-1, -1, -1):
        if (i > i2) or (i < i1) or (lines[i].find('unknown') == start): del lines[i]
        else:
          if '*' in lines[i][:start-1]: lines[i] = '   [X]  '+lines[i][start:]
          else: lines[i] = '   [  ]  '+lines[i][start:]
      lines.insert(0, 'Features (enabled/suported):')
      if len(RData) > 0: RData = RData + '\n'
      RData = RData + '\n'.join(lines)
    else:
      lines = result.stderr.splitlines()
      lines = [line for line in lines if line.strip()]
      hdparm_err = '\n'.join(lines)
      if len(RData) > 0: RData = RData + '\n'
      RData = RData + '---Hdparm:\n'+hdparm_err
    if len(RData) > 0: RData = RData + '\n'
    return RData

  def SendDevices():
    with devLock:
      UpdateBlockDevices()
      SendBuff(CMD_DEVICES, PackBlockDevices())

  def SendSysLog():
    try:
      with logLock:
        with open(LogEventsFile, 'rb') as logfile:
          buff = logfile.read()
      SendBuff(CMD_SYSLGET, buff)
    except Exception as E:
      if Debug: print(f'SendSysLog error: {E}')

  def ClearSysLog():
    try:
      with logLock:
        with open(LogEventsFile, 'w'): pass
    except Exception as E:
      if Debug: print(f'ClearSysLog error: {E}')

  # --- RealTime Info Thread -------------------

  def RTInfoThread(SelfObj, EndFlag, Access):
    Terminated = False; failures = 0
    while not Terminated:
      if SendBuff(CMD_RTINFO, PackRealTimeInfo()):
        failures = 0
        if Debug: print('RTI Send: success')
      else:
        failures += 1
        if Debug: print('RTI Send: failed')
      if failures == 3: break
      Terminated = EndFlag.wait(2.5)
    if Debug: print('RTI Thread stopped.')
    if Access.acquire(blocking=False):
      SelfObj[0] = None
      Access.release()

  def PackRealTimeInfo():
    CpuLoad = psutil.cpu_percent(interval=0.4)
    MemUsed = psutil.virtual_memory().percent
    UpTime = round(time.time() - BootTime)
    try:
      with i2cLock:
        UPS = I2CBus.read_i2c_block_data(PicoAddr, regMain, 13)
    except: UPS = [0x00] * 13
    try:
      REG_IntTmp = IntTemp.Temperature()
      REG_HddTmp = HddTemp.Temperature()
      REG_ExtTmp = ExtTemp.Temperature()
    except:
      REG_IntTmp = 0
      REG_HddTmp = 0
      REG_ExtTmp = 0
    return struct.pack('<ddQHHHHHB', CpuLoad, MemUsed, UpTime, CoreTemp, REG_IntTmp, REG_HddTmp, REG_ExtTmp, FanRpm, FanDuty) + bytes(UPS)

  def StartRTI():
    global AppOpened
    with devLock:
      SendBuff(CMD_DEVICES, PackBlockDevices())
    with rtiLock:
      AppOpened = True
      if RTIThread[0] == None:
        RTIEnd.clear()
        RTIThread[0] = threading.Thread(target=RTInfoThread, args=(RTIThread, RTIEnd, rtiLock), name='Real Time Info')
        RTIThread[0].start()

  def StopRTI():
    global AppOpened
    with rtiLock:
      AppOpened = False
      if RTIThread[0] != None:
        RTIEnd.set()
        RTIThread[0].join()
        RTIThread[0] = None

  # --- Remote Terminal Class ----------------------

  class RemoteTerminal(threading.Thread):
    CmdStat = [['Not yet executed', YELLOW], ['Command aborted', YELLOW], ['Failed to complete', RED], ['Completed successfully', GREEN]]

    def __init__(self, cmdlist, title):
      super().__init__(name='Remote Terminal')
      self.cmdlist = cmdlist  # element: [ 0:cmdstr or function, 1:status, 2:returncode, 3:title, 4:func_param_list, 5:func_result ]
      self.title = title
      self.process = None; self.m_in = None; self.m_out = None
      self.input_open = threading.Event()
      self.terminated = threading.Event()
      self.start()

    def Terminate(self):
      if self.is_alive():
        self.terminated.set()
        if self.process != None: self.process.terminate()
        self.join()

    def WriteInput(self, stdin_bytes):
      if self.is_alive() and self.input_open.is_set():
        print('Buff = ', ' '.join(['{:02x}'.format(byte) for byte in stdin_bytes]).upper())
        os.write(self.m_in, stdin_bytes)

    def SendLine(self, Msg, color=RESET, header=False):
      if header: Msg = '--- '+Msg+' '+((88 - len(Msg) - 5) * '-')
      Msg = color+Msg+'\r\n'+RESET
      SendBuff(CMD_STDOUTBUFF, Msg.encode('utf-8'))

    def run(self):
      def _RunCmd(command):   # return: 1-aborted, 2-failed, 3-success / returncode
        self.m_in,  s_in  = pty.openpty()
        self.m_out, s_out = pty.openpty()
        try:
          command = command.split()
          if command[0] == 'SHELL:':
            use_shell = True
            command = ' '.join(command[1:])
          else: use_shell = False
          if self.terminated.is_set(): return 1, 0
          self.process = subprocess.Popen(command, shell=use_shell, stdin=s_in, stdout=s_out, stderr=s_out)
          self.input_open.set()
          while self.process.poll() is None:
            data = b''
            while self.m_out in select.select([self.m_out], [], [], 0.05)[0]:
              B = os.read(self.m_out, 1024)
              if (B == None) or (len(B) < 1): break
              data += B
            if len(data) > 0: SendBuff(CMD_STDOUTBUFF, data)
          self.process.wait()
          if self.terminated.is_set(): return 1, self.process.returncode
          elif self.process.returncode == 0: return 3, 0
          else: return 2, self.process.returncode
        except Exception as E:
          if self.process != None: self.process.wait()
          self.SendLine(f'\r\nInternal Exception: {E}')
          return 2, 0
        finally:
          self.input_open.clear()
          os.close(self.m_in);  os.close(s_in)
          os.close(self.m_out); os.close(s_out)

      self.SendLine(self.title, GREEN, True)
      os.environ['PYTHONUNBUFFERED'] = '1'
      os.environ['COLUMNS'] = '200'
      os.environ['LINES'] = '200'
      Stat = 0; Code = 0
      try:
        for idx, cmd in enumerate(self.cmdlist):
          if cmd[3] != '': self.SendLine(cmd[3])
          if callable(cmd[0]): Stat, Code = cmd[0](self.cmdlist, idx, self.terminated)
          else: Stat, Code = _RunCmd(cmd[0])
          cmd[1] = Stat; cmd[2] = Code
          if Stat != 3: break
      finally:
        os.environ.pop('PYTHONUNBUFFERED', None)
        os.environ.pop('COLUMNS'); os.environ.pop('LINES')
        self.SendLine(f'{self.CmdStat[Stat][0]}. Exit code: {Code}', self.CmdStat[Stat][1], True)
        self.SendLine('')

  # --- Remote Terminal Commands ------------------------

  def RemoveMPoint(list, idx, endflag):
    try:
      mpoint = list[idx][4][0]
      err = ChangeFileLines('/etc/fstab', [], [mpoint])
      if err != '':
        Terminal.SendLine('Failed to update /etc/fstab): '+err)
        return 2, 1
      err = CheckMount(mpoint)
      if err != '':
        Terminal.SendLine(err)
        return 2, 2
      if os.path.exists(mpoint):
        try:
          os.rmdir(mpoint)
          return 3, 0
        except Exception as E:
          Terminal.SendLine(f'Cannot remove mount folder: {E}')
          return 2, 3
      else: return 3, 0
    except Exception as E:
      Terminal.SendLine(f'Internal exception: {E}')
      return 2, 10

  def AddMPoint(list, idx, endflag):
    try:
      uuid   = list[idx][4][0]
      mpoint = list[idx][4][1]
      fstype = list[idx][4][2]
      err = NasSysDir(mpoint)
      if err != '':
        Terminal.SendLine(err)
        return 2, 1
      mnt_line = f'UUID={uuid} {mpoint} {fstype} defaults,noatime,nodiratime,nofail,async 0 0'
      err = ChangeFileLines('/etc/fstab', [mnt_line], [mpoint])
      if err != '':
        Terminal.SendLine('Failed to update /etc/fstab): '+err)
        return 2, 2
      return 3, 0
    except Exception as E:
      Terminal.SendLine(f'Internal exception: {E}')
      return 2, 10

  # --- Client Handler -------------------------------

  def HandleClient(Conn):
    global AndroMsgPool, AMPModified
    nonlocal TCPRestart, LastCMD, Terminal

    def ReadSmallStr(raw=False):
      nonlocal Conn
      Buff = Conn.recv(1)
      Size = int.from_bytes(Buff, byteorder='big')
      if Size > 0:
        Buff = Conn.recv(Size)
        if raw: return Buff
        else: return Buff.decode('utf-8')
      else:
        if raw: return b''
        else: return ''

    def ReadWStr():
      nonlocal Conn
      Buff = Conn.recv(2)
      Size = struct.unpack('<H', Buff)[0]
      if Size > 0:
        Buff = Conn.recv(Size)
        return Buff.decode('utf-8')
      else: return ''  

    def ReadCmdBuff():
      nonlocal Conn
      BSize = int.from_bytes(Conn.recv(4), byteorder='little')
      if BSize > 0: return Conn.recv(BSize)
      else: return b''

    def SendResult(Status):
      nonlocal Conn
      if Status: Conn.sendall(MakeCMD(CMD_SUCCESS))
      else: Conn.sendall(MakeCMD(CMD_FAILED))

    if Debug: print('Client enter.')
    try:
      Conn.settimeout(1)
      while True:
        CMD = Conn.recv(4);
        if len(CMD) < 4: break
        if CMD == CMD_TESTMSG:
          if Debug: print(f'Received CMD: [{CMD.hex()}]')
          Conn.sendall(CMD_SUCCESS)
          continue
        if not FromComp(CMD) and not FromAndro(CMD):
          if Debug: print(f'Received CMD: [{CMD.hex()}] from unknown source')
          break
        CMD = GetCMD(CMD); LastCMD = CMD
        if Debug: print(f'Received CMD: [{CMD.hex()}]')

        # ----- COMP Commands ------------------------------------

        if CMD == CMD_SRVRST: TCPRestart = True
        elif CMD == CMD_RTISTART: StartRTI()
        elif CMD == CMD_RTISTOP: StopRTI()
        elif CMD == CMD_READPF: PowerFailureMsgHandler()
        elif CMD == CMD_INSTCHECK: SendBuff(CMD_INSTCHECK, GetInstStatus(), False)

        elif CMD == CMD_GETBATVI:
          DataBuff = bytearray(5762)
          with i2cLock: Res = ReadI2CBuff(cmdReadBat, DataBuff)
          if Res != None: SendBuff(CMD_GETBATVI, DataBuff)

        elif CMD == CMD_GETUPSTERM:
          DataBuff = bytearray(5762)
          with i2cLock: Res = ReadI2CBuff(cmdReadTerm, DataBuff)
          if Res != None: SendBuff(CMD_GETUPSTERM, DataBuff)

        elif CMD == CMD_GETNASTERM:
          with tmbLock: SendBuff(CMD_GETNASTERM, TermBuff)

        elif CMD == CMD_SYSLGET:
          SendSysLog()

        elif CMD == CMD_SYSLCLR:
          ClearSysLog()
          SendSysLog()

        elif CMD == CMD_CNTDOWN:
          if SDcounter > 0:
            SendBuff(CMD_CNTDOWN, struct.pack('<H', SDcounter), False, True)

        # ----- Exit requests ------------------------------

        elif CMD == CMD_NASRST: MainExit(exRestartNAS)
        elif CMD == CMD_NASSHD: MainExit(exShutdownNAS)
        elif CMD == CMD_UPSRST: MainExit(exRestartUPS, struct.unpack('<H', Conn.recv(2))[0])
        elif CMD == CMD_UPSSHD: MainExit(exShutdownUPS)
        elif CMD == CMD_ALLSHD: MainExit(exShutdownALL)

        elif CMD == CMD_DEBUG1: SendDebug1(True)    # Debug!

        # ----- Devices ------------------------------------

        elif CMD == CMD_DEVICES: SendDevices()

        elif CMD == CMD_DINFO:
          dev_node = ReadSmallStr()
          SendBuff(CMD_DINFO, PackSStr(DevSerial(dev_node)) + PackStr(GetDevInfo(dev_node)), False)
          UpdatePowerStatus(dev_node)

        elif CMD == CMD_SMART:
          dev_node = ReadSmallStr()
          Attrs, Err = GetSMART(dev_node)
          if Attrs != None:
            SPack, Err = PackSMART(Attrs)
            if SPack != None:
              SPack = struct.pack('<I', len(SPack)) + SPack
              Health, Err = GetHealth(dev_node)
          if Err != None: SendMessageToComp(CMD_MESSAGE, Err, 3)
          else: SendBuff(CMD_SMART, PackSStr(DevSerial(dev_node)) + PackSStr(Health) + SPack, False)
          UpdatePowerStatus(dev_node)

        elif CMD == CMD_GETAPM:
          dev_node = ReadSmallStr()
          send = False
          APM, Err = GetAPM(dev_node)
          if APM == None:
            SendMessageToComp(CMD_MESSAGE, Err, 3)
          else:
            with devLock:
              I = GetDiskIndex(dev_node)
              if (I != None) and (DevList[I][7] == 0):
                DevList[I][7] = int(APM != 0x200) + 1
                send = True
                with cfgLock:
                  Config['ApmAvail'][DevList[I][2]] = 'no' if APM == 0x200 else 'yes'
                  SaveConfig()
            SendBuff(CMD_GETAPM, PackSStr(DevSerial(dev_node)) + struct.pack('<H', APM), False)
          if UpdatePowerStatus(dev_node, False) or send:
            with devLock: SendBuff(CMD_DEVICES, PackBlockDevices())

        elif CMD == CMD_SETLABEL:
          part_node = ReadSmallStr()
          label = ReadSmallStr()
          with devLock:
            uuid, fstype, mpoint = PartMountInfo(part_node)
            if (uuid != None) and (len(uuid) > 0):
              if ('ext' in fstype) and (len(mpoint) == 0):
                Level, ResMsg = SetLabel(part_node, label)
                D, P = GetPartIndex(part_node)
                UpdatePowerStatus(DevList[D][1], False)
                UpdateBlockDevices()
                SendBuff(CMD_DEVICES, PackBlockDevices())
                SendMessageToComp(CMD_MESSAGE, ResMsg, Level)

        elif CMD == CMD_MOUNT:
          dev_node = ReadSmallStr()
          p_uuid = ReadSmallStr()
          p_name = ReadSmallStr()
          p_fstype = ReadSmallStr()
          SwitchToActive(dev_node)
          Level, ResMsg = MountPart(p_uuid, p_name, p_fstype)
          SendMessageToComp(CMD_MESSAGE, ResMsg, Level)

        elif CMD == CMD_UNMOUNT:
          dev_node = ReadSmallStr()
          mpoint = ReadSmallStr()
          SwitchToActive(dev_node)
          Level, ResMsg = UnmountPart(mpoint)
          SendMessageToComp(CMD_MESSAGE, ResMsg, Level)

        elif CMD == CMD_UNLOCK:
          dev_node = ReadSmallStr()
          mpoint = ReadSmallStr()
          SwitchToActive(dev_node)
          PerMan.AddTask(dev_node, mpoint)

        elif CMD == CMD_SLEEP:
          dev_node = ReadSmallStr()
          SwitchToStandby(dev_node)

        # ----- Terminal -------------------------

        elif CMD == CMD_STDINBUFF:
          stdin_buff = ReadSmallStr(True)
          if Terminal != None: Terminal.WriteInput(stdin_buff)

        elif CMD == CMD_TERMABORT:
          if Terminal != None: Terminal.Terminate()

        elif CMD == CMD_UPGRADE:
          Busy = (Terminal != None) and Terminal.is_alive()
          if not Busy:
            Cmds = [['apt-get update', 0, 0, 'Updating...'], ['apt-get upgrade', 0, 0, 'Upgrading...']]
            Terminal = RemoteTerminal(Cmds, 'Upgrading Raspberry Pi operating system')

        elif CMD == CMD_SMBSTOP:
          Busy = (Terminal != None) and Terminal.is_alive()
          if not Busy:
            Cmds = [['systemctl stop smbd nmbd', 0, 0, 'Stopping SMB and NMB Daemons...'],
                    ['SHELL: systemctl status smbd nmbd | grep -E "Loaded:|Active:"', 0, 0, 'CURRENT STATUS:']]
            Terminal = RemoteTerminal(Cmds, 'Stopping Samba server')

        elif CMD == CMD_SMBSTART:
          Busy = (Terminal != None) and Terminal.is_alive()
          if not Busy:
            Cmds = [['systemctl start smbd nmbd', 0, 0, 'Starting SMB and NMB Daemons...'],
                    ['SHELL: systemctl status smbd nmbd | grep -E "Loaded:|Active:"', 0, 0, 'CURRENT STATUS:']]
            Terminal = RemoteTerminal(Cmds, 'Starting Samba server')

        elif CMD == CMD_SMBRESTART:
          Busy = (Terminal != None) and Terminal.is_alive()
          if not Busy:
            Cmds = [['systemctl restart smbd nmbd', 0, 0, 'Restarting SMB and NMB Daemons...'],
                    ['SHELL: systemctl status smbd nmbd | grep -E "Loaded:|Active:"', 0, 0, 'CURRENT STATUS:']]
            Terminal = RemoteTerminal(Cmds, 'Restarting Samba server')

        elif CMD == CMD_SMBSTATUS:
          Busy = (Terminal != None) and Terminal.is_alive()
          if not Busy: Terminal = RemoteTerminal([['SHELL: systemctl status smbd nmbd | grep -E "Loaded:|Active:"', 0, 0, 'CURRENT STATUS:']], 'Samba server status')

        elif CMD == CMD_CHECKSTB:
          dev_node = ReadSmallStr()
          Busy = (Terminal != None) and Terminal.is_alive()
          if not Busy:
            Cmds = [[f'/usr/sbin/smartctl -n standby {dev_node}', 0, 0, '']]
            Terminal = RemoteTerminal(Cmds, f'Checking {dev_node} standby state')

        elif CMD == CMD_REPAIRFS:
          dev_node = ReadSmallStr()
          Busy = (Terminal != None) and Terminal.is_alive()
          if not Busy:
            with devLock: uuid, fstype, mpoint = PartMountInfo(dev_node)
            if (uuid != None) and (len(uuid) > 0) and ('ext' in fstype):
              if len(mpoint) == 0:
                Cmds = [[f'e2fsck -p {dev_node}', 0, 0, '']]
              else: Cmds = [
                [f'umount -v {mpoint[1]}', 0, 0, f'Unmounting the partition {dev_node}...'],
                [RemoveMPoint, 0, 0, 'Removing mountpoint...', [mpoint[1]], None],
                [f'e2fsck -p {dev_node}', 0, 0, ''],
                [AddMPoint, 0, 0, 'Adding mountpoint...', [uuid, mpoint[1], mpoint[2]], None],
                [f'mount -v {mpoint[1]}', 0, 0, f'Mounting back the partition {dev_node}...'],
                ['systemctl daemon-reload', 0, 0, 'Reloading systemd...']]
              Terminal = RemoteTerminal(Cmds, f'Checking {dev_node} for errors')

        # ----- Config (sync) ------------------------------

        elif CMD == CMD_SETNETCFG:
          CIP = ReadSmallStr(); CPort = ReadSmallStr()
          RIP = ReadSmallStr(); RPort = ReadSmallStr()
          Res = SetNetworkCfg(CIP, CPort, RIP, RPort)
          SendResult(Res);
          if Res: TCPRestart = True

        elif CMD == CMD_SETSTBCFG:
          StbBuff = ReadCmdBuff()
          SendResult(SetStbConfig(StbBuff));
          with devLock: SendBuff(CMD_DEVICES, PackBlockDevices())

        elif CMD == CMD_SETAPMCFG:
          ApmBuff = ReadCmdBuff()
          SendResult(SetApmConfig(ApmBuff));
          with devLock: SendBuff(CMD_DEVICES, PackBlockDevices())

        elif CMD == CMD_SETNOTCFG:
          NotifBuff = ReadCmdBuff()
          if len(NotifBuff) == ((13*3)+3): SendResult(SetNotifConfig(NotifBuff))
          else: SendResult(False)

        elif CMD == CMD_SETNFANCFG:
          FanBuff = ReadCmdBuff()
          if len(FanBuff) == 11: SendResult(SetNasFanConfig(FanBuff))
          else: SendResult(False)

        elif CMD == CMD_SETUFANCFG:
          FanBuff = ReadCmdBuff()
          if len(FanBuff) == 11:
            try:
              time.sleep(0.15)
              with i2cLock: I2CBus.write_i2c_block_data(PicoAddr, regFanCfg, list(FanBuff))
              if Debug: print(' UPS Fan settings passed to UPS')
              SendResult(True)
            except Exception as E:
              if Debug: print(f' Failed: {E}')
              SendResult(False)
          else: SendResult(False)

        elif CMD == CMD_SETSILCFG:
          SilBuff = ReadCmdBuff()
          if len(SilBuff) == 13:
            NBuff = SilBuff[:9] + SilBuff[11:13]; UBuff = SilBuff[:-2]
            if SetSilentConfig(NBuff):
              try:
                time.sleep(0.15)
                with i2cLock: I2CBus.write_i2c_block_data(PicoAddr, regSilentCfg, list(UBuff))
                if Debug: print(' Silent Mode settings passed to UPS')
                SendResult(True)
              except Exception as E:
                if Debug: print(f' Failed: {E}')
                SendResult(False)
            else: SendResult(False)
          else: SendResult(False)

        elif CMD == CMD_SETBATCFG:
          BatBuff = ReadCmdBuff()
          if len(BatBuff) == 14:
            try:
              with i2cLock:
                time.sleep(0.15)
                MainBuff = I2CBus.read_i2c_block_data(PicoAddr, regMain, 13)
                BatVoltage = struct.unpack('<HHHHHBH', bytes(MainBuff))[0] - 50
                CriticalLevel = struct.unpack('<HHHHHHH', BatBuff)[2]
                if Debug: print(f'VBat = {BatVoltage}  Critical = {CriticalLevel}')
                if BatVoltage < CriticalLevel:
                  SendMessageToComp(CMD_MESSAGE, 'The battery settings were not updated because it would generate a power failure !', 2)
                  if Debug: print(' Battery settings not updated !')
                else:
                  time.sleep(0.15)
                  I2CBus.write_i2c_block_data(PicoAddr, regBatCfg, list(BatBuff))
                  if Debug: print(' Battery settings passed to UPS')
              SendResult(True)
            except Exception as E:
              if Debug: print(f' Failed: {E}')
              SendResult(False)
          else: SendResult(False)

        elif CMD == CMD_SETBATLOW:
          BatBuff = ReadCmdBuff()
          if len(BatBuff) == 2:
            try:
              with i2cLock:
                time.sleep(0.15)
                I2CBus.write_i2c_block_data(PicoAddr, regBatLow, list(BatBuff))
                if Debug: print(' UPS BatLow updated')
              SendResult(True)
            except Exception as E:
              if Debug: print(f' Failed: {E}')
              SendResult(False)
          else: SendResult(False)  

        elif CMD == CMD_GETSMBPATH:
          SharePath = '\\\\'+socket.gethostname()+'\\'+NasName
          Conn.sendall(PackSStr(SharePath))

        # ----- ANDROID Commands ------------------------------------

        elif CMD == CMD_SETTOKEN:
          Token = ReadWStr()
          SendResult(SetAppTokenCfg(Token))

        elif CMD == CMD_SETLINK:
          Link = ReadWStr()
          SendResult(SetFCMLinkCfg(Link))

        elif CMD == CMD_GETAMPOOL:
          with ampLock:
            bSize = struct.pack('<I', len(AndroMsgPool))
            Conn.sendall(bSize + AndroMsgPool)
            if Conn.recv(4) == CMD_SUCCESS: 
              AndroMsgPool = b''
              AMPModified = False
              try: os.remove(AMPFile)
              except: pass


        # ---------------------------------------------------

    except Exception as E:
      if Debug:
        print(f'TCP Server exception (handle):')
        traceback.print_exception(type(E), E, E.__traceback__)
    finally:
      Conn.close()
      if Debug: print('Client exit.\n')

  # --- Server thread main cycle -----------------------------

  global BindedAddr
  RTIEnd = threading.Event()
  RTIThread = [None]
  PerMan = PermissionManager()

  LastCMD = CMD_NONE
  if Debug: print('TCP Server thread started.')
  try:
    TCPRestart = True
    while not EndFlag.is_set() and TCPRestart:
      TCPRestart = False

      AdpList = GetAdapterList()
      if len(AdpList) == 0:
        if Debug: print(RED + 'TCP Server error: This system has no network adapter.' + RESET)
        return
      SrvAddr = ValidRaspiAddr()
      if SrvAddr == None:
        if Debug: print(RED + 'TCP Server error: Invalid server address.' + RESET)
        return

      if SrvAddr[0] == 'none': 
        SrvAddr = (AdpList[0][1], SrvAddr[1])
        if Debug: print(YELLOW + f'TCP Server: No network adapter configured. Using first available.' + RESET)
      elif not any(adp[1] == SrvAddr[0] for adp in AdpList):
        SrvAddr = (AdpList[0][1], SrvAddr[1])
        if Debug: print(YELLOW + 'TCP Server: Configured network adapter not available. Using default.' + RESET)

      Terminal = None
      with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as SSocket:
        try:
          SSocket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
          SSocket.bind(SrvAddr); BindedAddr = SrvAddr
          SSocket.listen(10)
          if Debug:
            print(GREEN + f'TCP Server is listening on {SrvAddr[0]} : {SrvAddr[1]} ...' + RESET)
          if LastCMD == CMD_SRVRST: SendMessageToComp(CMD_MESSAGE, SrvResetStr, 1)
          try:
            while not EndFlag.is_set() and not TCPRestart:
              Conn, Addr = SSocket.accept()
              if EndFlag.is_set(): break
              HandleClient(Conn)
          except Exception as E1:
            if Debug: print(RED + f'TCP Server exception (listen): {E1}' + RESET)
          finally:
            if Terminal != None: Terminal.Terminate()
            if Debug: print(YELLOW + 'TCP Server has stopped listening.' + RESET)
        except Exception as E2:
          if Debug: print(RED + f'TCP Server exception (setup): {E2}' + RESET)

  finally:
    StopRTI()
    PerMan.Terminate()
    if Debug: print('TCP Server thread ended.')


# =============== MAIN ASYNC TASK ==========================================

async def StartInitTask():
  global TCPSrv, EventsEnabled, DevMon
  TaskEnter('Start Init')
  try:
    adpDone = False; botDone = False
    count = (8 * 60) // 2
    CompAddr = ValidCompAddr()
    conDone = CompAddr == None
    if Debug: print(f'Comp Server addr: {CompAddr}')

    for i in range(count):
      if not adpDone: adpDone = len(GetAdapterList()) > 0
      if not conDone: conDone = Connectable(CompAddr)
      if not botDone: botDone = BootDone()
      if Debug: print(f'CON={conDone}  ADP={adpDone}  BOOT={botDone}')
      if botDone and ((REG_Shutdown == stShdLow) or (REG_Shutdown == stShdNow)):
        MainExit(exShutdownUPS); return
      if (Debug or conDone) and adpDone and botDone: break
      await asyncio.sleep(2)
      if AsyncTerminated: return

    with devLock:
      if Debug and not StartInStandby: print('Waking up all disks...')
      UpdateBlockDevices()
      if Debug:
        print('')
        ShowDiskInfo()
        ShowStatInfo()
        print(f'Check Period = {CheckPeriod} seconds\n')

    TCPSrv = threading.Thread(target=ServerThread, args=(TCPSrvEnd,), name='TCP Server')
    TCPSrv.start()
    await asyncio.sleep(0.5)

    SendBackOnline()
    PowerFailureMsgHandler()
    if (REG_Shutdown == stShdLow) or (REG_Shutdown == stShdNow):
      MainExit(exShutdownUPS); return
    EventsEnabled = True
    DevMon = BlockDevMonitor(OnDevUpdate)
    SendRaspiReady()
    loop = asyncio.get_running_loop()
    loop.call_later(3, ShowAllThreads)

    TaskList.append(asyncio.create_task(DevicesTask()))
  except asyncio.CancelledError: pass
  finally: TaskExit('Start Init')


async def PicoRTCSyncTask():
  global PiSynced, SoundEn, FanDuty
  TaskEnter('Pico RTC Sync')
  try:
    while not AsyncTerminated:
      if ClockSynced():
        if not PiSynced:
          PiSynced = True
          RestoreGraphs()
          SoundEn = GetSoundEn()
          if not SoundEn and FanDuty > MaxFDuty:
            FanDuty = MaxFDuty
            FanPWM.SetDuty(FanDuty)
        if UpdatePicoRTC(): break
      for i in range(5):
        await asyncio.sleep(2)
        if AsyncTerminated: return
  except asyncio.CancelledError: pass
  finally: TaskExit('Pico RTC Sync')


async def ThermalTask():
  global CoreTemp, FanRpm, FanDuty
  TaskEnter('Thermal')
  try:
    CoreAvgS = AverageInt(3)
    CoreAvgL = AverageInt(15)
    while not AsyncTerminated:
      FanRpm = GetRPM()
      Temp = ReadCoreTemp()
      CoreAvgS.add_data(Temp); CoreAvgL.add_data(Temp)
      CoreTemp = CoreAvgS.get_avg(); DTemp = CoreAvgL.get_avg()
      DC = round(GetDutyCycle(DTemp))
      if NasFAuto: DC = FilterDC(DC, 5)
      if not SoundEn and DC > MaxFDuty: DC = MaxFDuty
      if DC != FanDuty:
        FanDuty = DC
        FanPWM.SetDuty(FanDuty)
      if False: # Debug:
        ftmp = float(CoreTemp) / 100
        print(f'AvgTemp = {ftmp:.2f} °C    RPM = {FanRpm}    Duty = {FanDuty} %')
      await asyncio.sleep(2)
  except asyncio.CancelledError: pass
  finally: TaskExit('Thermal')

# Debug!
def SendDebug1(Asked):
  global SDRList
  if len(SDRList) > 0:
    SDMsg = ''
    for event in SDRList:
      SDMsg += f'[{event[0]} - {event[1]}], '
    if SendMessageToComp(CMD_MESSAGE, SDMsg, 2) >= 0: SDRList = []
  elif Asked: SendMessageToComp(CMD_MESSAGE, 'List empty !', 1)

async def TimerTask():
  global TDcounter, SEcounter, SDcounter, SoundEn
  TaskEnter('Timer')
  try:
    while not AsyncTerminated:
      if TDcounter >= 60:
        with tmbLock: AddDataValues(TermBuff, CoreTemp, FanDuty)
        TDcounter = 0
      if SEcounter >= 60:
        SoundEn = GetSoundEn()
        SEcounter = 0
        SendDebug1(False)  # Debug!
      await asyncio.sleep(2)
      if SDcounter > 0:
        SDcounter -= 2
        if SDcounter <= 0:
          if Debug: print('Low battery shutdown')
          MainExit(exShutdownUPS)
      TDcounter += 2; SEcounter += 2
  except asyncio.CancelledError: pass
  finally: TaskExit('Timer')


async def UPSEventsTask():
  global REG_Shutdown, REG_Power, REG_Battery, REG_BatOver, SDcounter
  TaskEnter('UPS Events')
  try:
    while not AsyncTerminated:
      await UPSEvent.wait()
      with upsLock: UPSEvent.clear()
      if AsyncTerminated: return

      ReadDone = False; RCount = 0
      while not ReadDone:
        try:
          with i2cLock: buff = I2CBus.read_i2c_block_data(PicoAddr, regAlert, 16)
          ReadDone = True
        except Exception as E: 
          if Debug: print(f'I2C read error: {E}')
          if RCount == 10: break
          else: RCount += 1
          await asyncio.sleep(0.2)
          if AsyncTerminated: return
      if not ReadDone: continue    

      NewRegShd = bytes(buff[:4])
      NewRegPwr = bytes(buff[4:8])
      NewRegBat = bytes(buff[8:12])
      NewRegOvr = bytes(buff[12:])

      if NewRegShd != REG_Shutdown:
        REG_Shutdown = NewRegShd
        if REG_Shutdown == stNone:
          SendBuff(CMD_CNTDOWN, b'\x00\x00', False, True)
          if Debug: print('Shutdown countdown canceled.')
          if EventsEnabled: BroadcastMsg(BatSafeMsg, 1)
          SDcounter = 0
        elif REG_Shutdown == stShdNow:
          if Debug: print('Shutdown NOW !')
          MainExit(exShutdownUPS)
        elif REG_Shutdown == stShdLow:
          if not SendBuff(CMD_CNTDOWN, struct.pack('<H', SDCountdown), False, True):
            if Debug: print('App not ready. Shutting down...')
            MainExit(exShutdownUPS)
          else:
            if Debug: print('Shutdown countdown started.')
            if EventsEnabled: BroadcastMsg(BatLowMsg, 2)
            SDcounter = SDCountdown + 4

      if NewRegPwr != REG_Power:
        REG_Power = NewRegPwr
        if REG_Power == stPowerON:
          if Debug: print('Power Supply: ON')
          if EventsEnabled: BroadcastMsg(MainAvailMsg, 1)
        elif REG_Power == stPowerOFF:
          if Debug: print('Power Supply: OFF')
          if EventsEnabled: BroadcastMsg(MainLostMsg, 2)
      if NewRegBat != REG_Battery:
        REG_Battery = NewRegBat
        if REG_Battery == stBatON:
          if Debug: print('Battery: ON')
          if EventsEnabled: BroadcastMsg(BatAvailMsg, 1)
        elif REG_Battery == stBatOFF:
          if Debug: print('Battery: OFF')
          if EventsEnabled: BroadcastMsg(BatLostMsg, 3)
      if NewRegOvr != REG_BatOver:
        REG_BatOver = NewRegOvr
        if REG_BatOver == stBatOver:
          if Debug: print('Warning: Battery overvoltage !')
          if EventsEnabled: BroadcastMsg(BatOvr1Msg, 3)
        elif REG_BatOver == stNone:
          if Debug: print('Battery overvoltage cleared.')
          if EventsEnabled: BroadcastMsg(BatOvr0Msg, 1)

  except asyncio.CancelledError: pass
  finally: TaskExit('UPS Events')


async def DevicesTask():
  TaskEnter('Devices')
  try:
    while not AsyncTerminated:
      with clkLock: count = CheckPeriod // 2
      while not AsyncTerminated and (count > 0):
        await asyncio.sleep(2)
        count -= 1
      if not AsyncTerminated:

        with devLock:
          SendDevUpdate = False
          UpdateCounters()
          for disk in DevList:
            new_count = GetDiskCount(disk[0])
            delta = new_count - disk[5][0]; disk[5][0] = new_count
            if (disk[4] == 2) and (disk[5][5] > 0) and (disk[5][3] == 1):  # we have a HDD with enabled KA in active state
              if delta == 0: disk[5][1] += 1                               #  is Idle ? Inc(KA)
              if disk[5][1] >= disk[5][5]:                                 #  KA period over ?
                IOs = KeepAlive(disk[1])                                   #   send KeepAlive
                disk[5][1] = 0; disk[5][0] += IOs                          #   reset KA and adjust IO count
            if delta > 0:      # we have activity
              disk[5][1] = 0; disk[5][2] = 0                               # Reset KA and Idle counters
              if (disk[4] == 2) and (disk[5][3] == 2):                     # we have a HDD in standby
                disk[5][3] = 1; disk[5][4] = 'active'                      #  mark it as active
                if disk[7] == 0: disk[7] = ApmAvailable(disk[2])           #  update APM Avail
                SetTargetAPM(disk)                                         #  update APM
                SendDevUpdate = True                                       #  mark for status update
            else:              # no disk activity
              disk[5][2] += 1                                              # Inc(Idle)
              if (disk[4] == 2) and (disk[5][6] > 0):                      # we have a HDD with enabled SB
                if (disk[5][3] == 1) and (disk[5][2] >= disk[5][6]):       #  if it is active and SB period is over
                  PutInStandby(disk[1])                                    #    put the drive in standby
                  disk[5][1] = 0                                           #    reset KA
                  disk[5][3] = 2; disk[5][4] = 'standby'                   #    mark inactive
                  UpdateCounters(); disk[5][0] = GetDiskCount(disk[0])     #    reset IO count
                  SendDevUpdate = True                                     #    mark for status update
          if Debug: ShowStatInfo()
          with rtiLock:
            if AppOpened or SendDevUpdate:
              SendBuff(CMD_DEVICES, PackBlockDevices())

  except asyncio.CancelledError: pass
  finally: TaskExit('Devices')


async def main():
  loop = asyncio.get_running_loop()
  loop.set_exception_handler(HandleAsyncExceptions)
  # DeviceTask() is started later
  TaskList.append(asyncio.create_task(StartInitTask()))
  TaskList.append(asyncio.create_task(ThermalTask()))
  TaskList.append(asyncio.create_task(TimerTask()))
  TaskList.append(asyncio.create_task(UPSEventsTask()))
  TaskList.append(asyncio.create_task(PicoRTCSyncTask()))
  await AllTasksDone.wait()
  if Debug: print('Main async task gracefully terminated.')

def HandleAsyncExceptions(loop, context):
  E = context['exception']
  if Debug:
    print('\n' + RED + 'Async Task exception:' + EXCEPT)
    traceback.print_exception(type(E), E, E.__traceback__)
    print(RESET)
  else:
    with open(LogExceptFile, 'a') as LogFile:
      DT = datetime.now()
      TimeStamp = '[ {:02d}-{:02d}-{:04d}, {:02d}:{:02d}:{:02d} ]'.format(DT.day, DT.month, DT.year, DT.hour, DT.minute, DT.second)
      LogFile.write(LineBreak+'\n')
      LogFile.write(TimeStamp+'\n')
      LogFile.write(LineBreak+'\n')
      LogFile.write('Async Task exception:\n')
      traceback.print_exception(type(E), E, E.__traceback__, file=LogFile)
  MainExit(exNone)

def TaskEnter(name):
  if Debug: print(f'Task: {name} started')

def TaskExit(name):
  CT = asyncio.current_task()
  if CT in TaskList: TaskList.remove(CT)
  if len(TaskList) == 0: AllTasksDone.set()
  if Debug: print(f'Task: {name} ended')


# =============== PROGRAM STARTING POINT ================================

LogD(4, 'Reaching program starting point')

# Set file paths...

RunPath = os.path.dirname(os.path.abspath(__file__))
CustomSettingsFile = RunPath+'/nas_settings.ini'
LogEventsFile = RunPath+'/nas_events.log'
LogExceptFile = RunPath+'/nas_except.log'
TermFile = RunPath+'/term.bin'
AMPFile  = RunPath+'/pool_andro.bin'
SafeShdFile = '/var/safe_shd'  # a flag file to detect power failures

CrontabCfg = [CrontabCfg[0].replace('%RunPath%', RunPath)]
RebootCfg  = [RebootCfg[0].replace('%RunPath%', RunPath)]
PwrOffCfg  = [PwrOffCfg[0].replace('%RunPath%', RunPath)]

LogD(5, 'Paths inited')

# Loading settings...

Config = configparser.ConfigParser()
Config.optionxform = str
Config.read_string(DefaultSettings)
Config.read(CustomSettingsFile)
CheckPeriod = Config['Standby'].getint('CheckPeriod')
LogD(6, 'Settings loaded')

# Init global variables and objects...

AsyncTerminated = False
EventsEnabled   = False
AppOpened       = False
PiSynced        = False
GraphsHandled   = False
BootTime        = psutil.boot_time()

ICount          = 0
RPM_StartTime   = 0
CoreTemp        = 0
FanRpm          = 0
FanDuty         = 0
ExitCmd         = exNone
ExitRSecs       = 0

NasFAuto        = True
LowTemp         = 3800
HighTemp        = 4100
LowDuty         = 20
HighDuty        = 100
FixDuty         = 50
DPG             = (HighDuty - LowDuty) / (HighTemp - LowTemp)

SilentMode      = True
SilentSTH       = 22
SilentSTM       = 30
SilentSPH       = 8
SilentSPM       = 0
MaxFDuty        = 40

SoundEn         = True
SEcounter       = 0

DataBuffSize    = 5762
DPosI           = DataBuffSize-2             # position start index
DPos1           = 0                          # first value start index
DPos2           = DPosI // 2                 # second value start index
TermBuff        = bytearray(DataBuffSize)    # last 24 hours Term Tmp*DC / 0.00 *C, 2-byte, 1 min / 2880 + 2880 + 2
TDcounter       = 0                          # number of seconds since last TermBuff update
SDcounter       = 0                          # shutdown countdown timer

# --- Debug! ---
SDRList      = []
LastSdReq    = 0

TCPSrv       = None
BindedAddr   = None
DevMon       = None
NAlert       = None
GpioMon      = None
I2CBus       = None
FanPWM       = None
SaveCfgTimer = None
UPSEvent     = asyncio.Event()
TCPSrvEnd    = threading.Event()
devLock      = threading.RLock()
cfgLock      = threading.RLock()
clkLock      = threading.RLock()
rtiLock      = threading.RLock()
i2cLock      = threading.RLock()
upsLock      = threading.RLock()
pflLock      = threading.RLock()
logLock      = threading.RLock()
tmbLock      = threading.RLock()  # TermBuff
ampLock      = threading.RLock()  # AndroMsgPool
UDEV         = pyudev.Context()
Counters     = ()
MountPoints  = ()

LogD(7, 'Global variables inited')

# Loading Msg Pools...

try:
  with open(AMPFile, 'rb') as ampFile:
    AndroMsgPool = ampFile.read()      # holds the messages sent to Android until the Android app gets them
except:
  AndroMsgPool = b''    
AMPModified  = False
LogD(8, 'Message pools loaded')

# Handling Restart/Shutdown/ServerAddr requests...

for param in ParamList:
  if param == '-shutdown':
    PowerOffHDDs()
    BroadcastMsg(ShutdownMsg, 3)
    SaveAndroMsgPool()
    SendBuff(CMD_THEEND, b'', False, False)
    time.sleep(0.5)
    SignalToCutThePower()
    sys.exit(0)
  elif param == '-reboot':
    PowerOffHDDs()
    BroadcastMsg(RebootMsg, 2)
    SaveAndroMsgPool()
    SendBuff(CMD_THEEND, b'', False, False)
    time.sleep(0.5)
    sys.exit(0)
  elif param == '-srvaddr':
    print(GetServerAddr())
    sys.exit(0)  

# Allow only one instace...

if AlreadyRunning():
  if Debug: print('Script is already running...\nUse "sudo htop" and F9 on the main thread to stop it.')
  sys.exit(1)
LogD(9, 'One instance allowed')  

# Handling Install/Remove requests...

IRNewUser = ''; IRNewPass = ''
for param in ParamList:

  if param.startswith('-install'):
    if not ':' in param: InstallScript(True, True, True)
    else: 
      opts = param.split(':')[1].split(',')
      ex_opts = 0
      for opt in opts:
        if opt.startswith('smbuser='): 
          IRNewUser = opt.split('=')[1]; ex_opts += 1; break
      for opt in opts:
        if opt.startswith('smbpass='): 
          IRNewPass = opt.split('=')[1]; ex_opts += 1; break
      if 'status' in opts:
        print('Script installation status:')
        ShowStatus(GetInstStatus())
      else:
        req_samba = 'samba' in opts; req_paths = 'paths' in opts; req_hwfeat = 'hwfeat' in opts 
        if not any([req_samba, req_paths, req_hwfeat]) and (len(opts) - ex_opts == 0):
          req_samba = True; req_paths = True; req_hwfeat = True 
        InstallScript(req_samba, req_paths, req_hwfeat)  
    sys.exit(0)

  elif param.startswith('-remove'):
    if not ':' in param: UninstallScript(True, True, True)
    else: 
      opts = param.split(':')[1].split(',')
      if 'status' in opts:
        print('Script installation status:')
        ShowStatus(GetInstStatus())
      else:
        req_samba = 'samba' in opts; req_paths = 'paths' in opts; req_hwfeat = 'hwfeat' in opts 
        UninstallScript(req_samba, req_paths, req_hwfeat)  
    sys.exit(0)

# Handling Standby flag...

StartInStandby = Debug
for param in ParamList:
  if param == '-disk:on':
    StartInStandby = False
  elif param == '-disk:off':
    StartInStandby = True
LogD(10, 'Standby flag handled')

# Check if the script is installed...

IStat = GetInstStatus(False)
LogD(11, f"Install Status = {''.join('0' if b == 0 else '1' for b in IStat)}")
if not all(value == 0x01 for value in IStat):
  if Debug: 
    print(CYAN+'Install Status: '+RED+'Not complete')
    print(YELLOW+'Please run the script again with "-install" parameter.')
    print('You can add options with ":" and "samba,paths,hwfeat,smbuser=<user>,smbpass=<pass>".'+RESET)
    print('')
    ShowStatus(IStat)
  LogD(11, 'App not properly installed. Exiting...')
  sys.exit(2)
LogD(11, 'Install check done')  

# Check Safe Shutdown flag

if not Debug:
  Sshd_Ack = WasSafeShd()
  if Sshd_Ack: ClearSafeShd()
LogD(12, 'Safe shutdown flag inited')  

# Register signal handlers...

def ExitRequest(signum, frame):
  if Debug: print('\nSignaled to terminate...')
  MainExit(exNone)

signal.signal(signal.SIGTERM, ExitRequest)
signal.signal(signal.SIGINT, ExitRequest)
LogD(13, 'Signal handlers registered')

try:
  LogD(14, 'Entering the main "try" block')
  if Debug: print(f'Run Path: {RunPath}')

  # Clearing the FirstRun flag...

  if not Debug:
    with cfgLock:
      if Config['General'].getboolean('FirstSysRun'):
        Config['General']['FirstSysRun'] = 'false'
        SaveConfig()
  LogD(15, 'FirstRun flag cleared')

  # Setting RealTime priority to the Main Thread and all its created sub-threads...

  MainPID = threading.get_native_id()
  priority = os.sched_get_priority_max(os.SCHED_FIFO)   # 1 (min) ... 99 (max)
  os.sched_setscheduler(MainPID, os.SCHED_FIFO, os.sched_param(priority))
  LogD(16, 'Priority set')

  # Init I2C Master bus...

  I2CBus = SMBus(1)
  LogD(17, 'I2C bus inited')

  # Thermal settings...

  FanPWM = HardwarePWM(channel=0, freq=25000)
  FanPWM.Start(0)
  ReadNasFanParams()
  IntTemp = TMP275(I2CBus, IntAddr, 12)
  HddTemp = TMP275(I2CBus, HddAddr, 12)
  ExtTemp = TMP275(I2CBus, ExtAddr, 12)
  LogD(18, 'Thermal configured')

  # Silent Mode settings...

  ReadSilentParams()
  LogD(19, 'Silen Mode params read')

  # Try init UPS Power state registers...

  REG_Shutdown = stNone
  REG_Power = stNone
  REG_Battery = stNone
  REG_BatOver = stNone
  try:
    with i2cLock:
      SBuff = I2CBus.read_i2c_block_data(PicoAddr, regAlert, 16)
    REG_Shutdown = bytes(SBuff[:4])
    REG_Power = bytes(SBuff[4:8])
    REG_Battery = bytes(SBuff[8:12])
    REG_BatOver = bytes(SBuff[12:])
  except: pass
  LogD(20, 'UPS regs inited')

  # Setting up GPIO ports and starting GPIO Monitor thread...

  NAlertConfig = { NAlertPin: gpiod.LineSettings(direction=Direction.INPUT, bias=Bias.PULL_UP) }
  NAlert = gpiod.request_lines(RPiChip, consumer='NAS-I2CAlert', config=NAlertConfig)
  GpioConfig = {
    SDReqPin:  gpiod.LineSettings(direction=Direction.INPUT, bias=Bias.PULL_UP,   edge_detection=Edge.BOTH),     # , debounce_period=timedelta(milliseconds=10)
    RpmPin:    gpiod.LineSettings(direction=Direction.INPUT, bias=Bias.PULL_UP,   edge_detection=Edge.FALLING),
    UAlertPin: gpiod.LineSettings(direction=Direction.INPUT, bias=Bias.PULL_DOWN, edge_detection=Edge.RISING) }
  GpioCallbacks = {
    SDReqPin:  SDRequest,
    RpmPin:    CountImpulses,
    UAlertPin: UPSAlert }
  GpioMon = GpioMonitor('NAS-GpioMonitor', GpioConfig, GpioCallbacks)
  LogD(21, 'GPIO inited')

  # Main thread Async Loop...

  ResetRPM()
  TaskList = []
  AllTasksDone = asyncio.Event()
  LogD(22, 'Entering main loop')
  asyncio.run(main())

except Exception as E:
  if Debug:
    print('\n' + RED + 'Main program exception:' + EXCEPT)
    traceback.print_exception(type(E), E, E.__traceback__)
    print(RESET)
  else:
    with open(LogExceptFile, 'a') as LogFile:
      DT = datetime.now()
      TimeStamp = '[ {:02d}-{:02d}-{:04d}, {:02d}:{:02d}:{:02d} ]'.format(DT.day, DT.month, DT.year, DT.hour, DT.minute, DT.second)
      LogFile.write(LineBreak+'\n')
      LogFile.write(TimeStamp+'\n')
      LogFile.write(LineBreak+'\n')
      LogFile.write('Main program exception:\n')
      traceback.print_exception(type(E), E, E.__traceback__, file=LogFile)

# If shutting down, inform UPS...

if ExitCmd >= exShutdownNAS:
  try:
    with i2cLock: I2CBus.write_i2c_block_data(PicoAddr, regShdState, [2])
    time.sleep(0.1)
  except: pass  

# Stop threads and cleanup...

if TCPSrv  != None: StopTCPServer()
if DevMon  != None: DevMon.Terminate()
if NAlert  != None: NAlert.release()
if GpioMon != None: GpioMon.Terminate()
if I2CBus  != None: I2CBus.close()
if FanPWM  != None: FanPWM.Stop()

BroadcastMsg(AppTermMsg, 2, [ExitStr[ExitCmd]])

# Save data if needed...

SaveConfigNow()                          # save app settings 
SaveAndroMsgPool()                       # save Android message pool
if not Debug: SaveGraphs()               # save graph buffers data
if not Debug and Sshd_Ack: SetSafeShd()  # mark safe shutdown

time.sleep(1)

# Do exit action...
if ExitCmd == exNone:
  SendBuff(CMD_THEEND, b'', False, False)
elif ExitCmd == exRestartNAS:
  os.system('sudo reboot')
elif ExitCmd == exShutdownNAS:
  NASMarkSD()
  os.system('sudo poweroff -p')
elif ExitCmd == exRestartUPS:
  UPSMarkRS(ExitRSecs)
  os.system('sudo poweroff -p')
elif ExitCmd == exShutdownUPS:
  UPSMarkSD()
  os.system('sudo poweroff -p')
elif ExitCmd == exShutdownALL:
  ALLMarkSD()
  os.system('sudo poweroff -p')


