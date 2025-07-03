
#---------------- Weather Station v1.0 -----------------#
#                                                       #
#   Created by: Marus Alexander (Romania/Europe)        #
#   Contact and bug report: marus.gradinaru@gmail.com   #
#   Website link: https://marus-gradinaru.42web.io      #
#   Donation link: https://revolut.me/marusgradinaru    #
#                                                       #
#-------------------------------------------------------#


ScriptVer  = '$version$:v1.0:'
Debug      = False

# --- User Configuration ------------

NET_SSID   = 'your_ssid'           ! Configure this section first !
NET_PASS   = 'your_pass'
TMZ_OFFSET = const(0)              # Time zone offset (hours)

# ------ Calibration -------------------

VRef       = 1507                  # Reference voltage (mV)
BDivR      = 2.50183               # Battery divisor network ratio
RTest      = 0.48964               # RI measurement, 0.5 ohms resistor (ohms)
RBplus     = 0.00914               # Parasite resistance on the battery positive power rail (ohms)
RBminus    = 0.03666               # Total resistance of battery protection mosfets + sens resistor + traces (ohms)
RBshunt    = 0.02153               # Shunt resistance in the battery protection circuit (ohms)
BCgain     = 15.92887              # The gain of the opamp used to measure the battery charging current
LDivR      = 2.50184               # Load divisor network ratio
RLshunt    = 0.020                 # Shunt resistance in the load ammeter circuit (ohms)
LIgain     = 10.00                 # The gain of the opamp used to measure the load current
BRatedCap  = 3200                  # Rated Li-ion cell capacity (mAh) - used to estimate self-discharge


# --- Big Buffers allocated first --- 

LDBSize    = const(2880)                # last day buff size: 24h * 60 min * 2 bytes
LVBuff     = bytearray(LDBSize)         # last 24 hours Load Voltage (mV)
LIBuff     = bytearray(LDBSize)         # last 24 hours Load Current (mA)
BVBuff     = bytearray(LDBSize)         # last 24 hours Bat Voltage (mV)
BIBuff     = bytearray(LDBSize)         # last 24 hours Bat Current (mA)
BTBuff     = bytearray(b'\x00\x80'*(LDBSize//2))  # last 24 hours Bat Temp (0.01 *C), inited to 0x8000 (-32768)
Sidx       = 0                          # start index in all buffers (oldest sample)
STCount    = 0                          # number of x2 seconds since last stored sample

html_page  = """\
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Weather Station</title>
  <style>
    body {font-family: sans-serif; padding: 0; background-color: black; margin: 0;
     display: flex; justify-content: center; align-items: center; min-height: 100vh;}
    #title {font-size: min(8.5vw, 70px); color: white; font-weight: bold; margin-bottom: 2%;}    
    #temp  {font-size: min(7.5vw, 60px); color: #FF3838; margin: 2% 0;}
    #dew   {font-size: min(7.5vw, 60px); color: #40DFDF; margin: 2% 0;}
    #hum   {font-size: min(7.5vw, 60px); color: #30BF30; margin: 2% 0;}
    #pres  {font-size: min(7.5vw, 60px); color: #BFBF10; margin: 2% 0;}
    #body-box {
      background-color: #202020;
      border: 2.5px solid gray; border-radius: 15px;
      padding: 2.5%;
      width: 93vw; max-width: 750px;
      box-sizing: border-box;
      text-align: center;
    }
  </style>
</head>
<body>
  <div id="body-box">
    <div id="title">Weather Station:</div>
    <div id="temp">Temperature: --- °C</div>
    <div id="dew">Dew Point: --- °C</div>
    <div id="hum">Humidity: --- %</div>
    <div id="pres">Pressure: --- mb</div>
  </div>
  <script>
    async function updateData() {
      try {
        const res = await fetch('/data');
        const json = await res.json();
        document.getElementById("temp").textContent = "Temperature: " + json.temp + " °C";
        document.getElementById("dew").textContent = "Dew Point: " + json.dew + " °C";
        document.getElementById("hum").textContent = "Humidity: " + json.hum + " %";
        document.getElementById("pres").textContent = "Pressure: " + json.pres + " mb";
      } catch (e) {
        console.log("Error:", e);
      }
    }
    setInterval(updateData, 6000);
    updateData();
  </script>
</body>
</html>
"""


# --- Import needed modules ----------

import sys, gc, time, struct, asyncio, os, network, ntptime, rp2, hashlib, platform, uctypes
from machine import Pin, I2C, RTC, reset
import Files, Devices


# ------- Configuration --------------

pinChgStat = const(0)
pinChgEn   = const(1)
pinPwrEn   = const(2)
pinTmpAlt  = const(3)
pinSensSda = const(4)
pinSensScl = const(5)
pinCSync   = const(6)
pinLedGrn  = const(7)
pinLedRed  = const(8)
pinShdReq  = const(9)
pinPwrSda  = const(10)
pinPwrScl  = const(11)
pinNetLed  = const(12)
pinLoadEn  = const(15)
pinBuzzer  = const(16)

LoadAddr   = const(0x48)           # Load VI ADC
BatAddr    = const(0x49)           # Battery VI ADC
TempAddr   = const(0x4F)           # Battery Temperature
BmeAddr    = const(0x76)           # BME Weather Sensor 
AhtAddr    = const(0x38)           # AHT Weather Sensor

RIUpdTime  = const(15)             # Number of days after the battery internal resistance is updated (measured again)


#------ Other constants ----------------

nbSize     = const(1024)           # Network buffer size

NoneTV     = b'\xFF\x7F'           # None value for temperatue 
NoneHV     = b'\xFF\xFF'           # None value for humidity 
NonePV     = b'\xFF\xFF'           # None value for pressure 

clNorm     = const(1)
clWarn     = const(2)
clCrit     = const(3)

ldLVI      = const(1)
ldBVI      = const(2)
ldBT       = const(3)

BTHyst     = const(2)              # Battery temperature hysteresis (°C)

srNone     = const(0)              # Battery "stop reason": no specific one  
srDone     = const(1)              # Battery "stop reason": charging complete
srTemp     = const(2)              # Battery "stop reason": temperature out of range

Months = ('January', 'February', 'March', 'April', 'May', 'June', \
  'July', 'August', 'September', 'October', 'November', 'December')


#------ Bat RI temp. comp. -------------

BC1 =  1.38042e-07
BC2 = -1.26304e-05
BC3 =  0.00086445
BC4 = -0.04655434
BC5 =  1.767

def BCRatio(T):
  return BC1 * T**4 + BC2 * T**3 + BC3 * T**2 + BC4 * T + BC5


#------ Used files ---------------------

MainProj   = '/MainProject.mpy'
IniFile    = '/config.ini'
PowerFile  = '/power_data.bin'
WDataFile  = '/wdata.bin'
ExceptFile = '/exception_log.txt'  # it will be read-only from outside
DebugFile  = '/debug_log.txt'


#------ Default settings ---------------

DefaultSettings = """\
[General]
LastRTC    = 0

[Network]
PicoPort   = 60401
CompIP     = none 
CompPort   = 60402

[Battery]
BatRI      = 70
BatRITS    = 0
ChargerEn  = no 
ChgIEnd    = 0
ChgStop    = 4070
ChgStart   = 3950
BatVOff    = 3500
FullCap    = 0.0
HoldCap    = 0.0
SelfDisTS  = 0 
TChgL      = 10.0
TChgH      = 43.0
TDisL      = -10.0
TDisH      = 55.0
"""

# ------ Task commands -----------------

tcChgStat   = const(0x5B)
tcShutdown  = const(0xE2)


# ------ TCP constants -----------------

COMP_CMDID    = const(0x3A)
PICO_CMDID    = const(0xB8)

CMD_NACK      = b'\xFF\x00\x00\x00' 
CMD_ACKN      = b'\xFF\x00\x3C\xA5'

CMD_ALIVE     = b'\xE9\x00\x01\x01'
CMD_VISIBLE   = b'\xE9\x00\x01\x02'
CMD_GETWDATA  = b'\xE9\x00\x01\x03'
CMD_SENDWDAY  = b'\xE9\x00\x01\x04'
CMD_GETTODAY  = b'\xE9\x00\x01\x05'

CMD_FLPQUERY  = b'\xE9\x00\x01\x11'
CMD_FLGET     = b'\xE9\x00\x01\x12'
CMD_FLSEND    = b'\xE9\x00\x01\x13' 
CMD_FLDEL     = b'\xE9\x00\x01\x14' 
CMD_FLRENAME  = b'\xE9\x00\x01\x15'
CMD_FLMKDIR   = b'\xE9\x00\x01\x16'

CMD_POWER     = b'\xE9\x00\x02\x01'
CMD_WEATHER   = b'\xE9\x00\x02\x02'
CMD_RTISTART  = b'\xE9\x00\x02\x03'
CMD_RTISTOP   = b'\xE9\x00\x02\x04'
CMD_MESSAGE   = b'\xE9\x00\x02\x05'
CMD_LOADVI    = b'\xE9\x00\x02\x06'
CMD_BATVI     = b'\xE9\x00\x02\x07'
CMD_BATTEMP   = b'\xE9\x00\x02\x08'
CMD_STATUS    = b'\xE9\x00\x02\x09'
CMD_EXCEPT    = b'\xE9\x00\x02\x0A'
CMD_MEMORY    = b'\xE9\x00\x02\x0B'
CMD_SETNETW   = b'\xE9\x00\x02\x0C'

CMD_GETBINFO  = b'\xE9\x00\x02\x11'
CMD_BSETCAP   = b'\xE9\x00\x02\x12'
CMD_BSETLVL   = b'\xE9\x00\x02\x13'
CMD_CHGENBL   = b'\xE9\x00\x02\x14'
CMD_CHGSTART  = b'\xE9\x00\x02\x15'
CMD_CHGSTOP   = b'\xE9\x00\x02\x16'
CMD_GETDRI    = b'\xE9\x00\x02\x17'
CMD_GETCRI    = b'\xE9\x00\x02\x18'
CMD_UPDATERI  = b'\xE9\x00\x02\x19'
CMD_BSETTMP   = b'\xE9\x00\x02\x1A'

CMD_RTCSYNC   = b'\xE9\x00\x02\x21'
CMD_TERMPROG  = b'\xE9\x00\x02\x22'
CMD_SENSRESET = b'\xE9\x00\x02\x23'

SC_ACKN   = b'\xE5\x21'
SC_FAIL   = b'\xE5\x22'
SC_NEXT   = b'\xE5\x23'
SC_DONE   = b'\xE5\x24'

SC_FILE   = b'\xE5\x41'
SC_SHA2   = b'\xE5\x42'
SC_DIR    = b'\xE5\x43'
SC_RET    = b'\xE5\x44'
SC_DEL    = b'\xE5\x45'


# ----- Message constants: Debug --------------

ErrorIncomplete = 'Incomplete data received'
ErrorAborted    = 'Operation aborted'
MsgCliConn      = 'Client connected'
MsgCliDisconn   = 'Client connection closed'
MsgWifiConning  = 'Connecting to WiFi...'
MsgWifiConned   = 'Connected to WiFi as: ' 
MsgExitGrace    = 'Main Program gracefully terminated.'

NetStatIdle     = 'No connection and no activity'
NetStatConning  = 'Connecting in progress'
NetStatWPass    = 'Failed due to incorrect password'
NetStatNoAP     = 'Failed because no access point replied' 
NetStatFail     = 'Failed due to other problems'
NetStatOK       = 'Connection successful'
NetStatUnkn     = 'Unknown newtwork status'

# ----- Message constants: ExLog --------------

ErrorCmdBuff    = 'Error in: '
ErrorExLog      = 'Error while sending Exception Log'
ErrorMemMap     = 'Error while sending Memory Map'
ErrorWDayUpload = 'Error while uploading weather day'
ErrorLDBuff     = 'Error while sending LD Buffs'
ErrorCliHand    = 'Error while handling network client'
ErrorHttp       = 'Error while handling HTTP request'
ErrorAsyncio    = 'AsyncIO general error'
ErrorInEntry    = 'Error in Entry code'
ErrorInExit     = 'Error in Exit code'

# ----- Message constants: Sent Files ------

ErrorNoPath     = 'Cannot find path'
ErrorCreateFile = 'Cannot create file'
ErrorOpenFile   = 'Cannot open file'
ErrorCloseFile  = 'Cannot close file'
ErrorReadFile   = 'Cannot read file'
ErrorWriteFile  = 'Cannot write to file'
ErrorRemFile    = 'Cannot remove file'
ErrorRenBack    = 'Cannot rename/backup'
ErrorRename     = 'Cannot rename'
ErrorListDir    = 'Cannot list folder'
ErrorMakeDir    = 'Cannot create folder'
ErrorRemDir     = 'Cannot remove folder'
ErrorMakePath   = 'Cannot create folders'
ErrorNoSpace    = 'Not enough disk space for'
ErrorSHAFail    = 'SHA256 does not match'
ErrorExLogRO    = 'The exception log is read only'

# ----- Message constants: Sent Notifs ------

MsgBackOnline   = 'Weather Station is back online'
MsgClkNotSync   = 'Warning: Clock is not synchronized !'
MsgClockBack    = 'Warning: The clock has been set back !'
MsgBatRIUpd     = 'Battery RI updated successfully:'
MsgRestBack     = 'System error: Restoring backup...'
MsgSysShd       = 'Weather Station has been shut down !'
MsgStartChg     = 'Battery charging has started.'
MsgStopChg      = 'Battery charging has stopped.'
MsgPowerLost    = 'Warning: Main power is lost !'
MsgPowerAvail   = 'Main power is now available.'
MsgBatTemp      = 'The battery temperature is outside normal limits: '

RTCAlSynced     = 'RTC is already synchronized: '
RTCSynced       = 'RTC has been successfully synchronized to: '

ErrorRIBatBusy  = 'Measuring RI test failed: Battery is not idle.'
ErrorDRIFail    = 'Discharging RI test failed: Battery is not idle.'
ErrorCRIFail    = 'Charging RI test failed: Battery is not idle.'
MsgRIUpdated    = 'Updated Internal Resistance:\n'
MsgDRIDone      = 'Measured Internal Resistance (while discharging):\n'
MsgCRIDone      = 'Measured Internal Resistance (while charging):\n'


# ----- Exceptions --------------------

class IncompleteData(Exception):
  def __init__(self):
    super().__init__(ErrorIncomplete)

class AbortWork(Exception):
  def __init__(self):
    super().__init__(ErrorAborted)


# ------ Bsic Function -----------------

def TimeStr():
  DT = PicoRTC.datetime()
  return '{} {} {:04d}, {:02d}:{:02d}:{:02d}'.format(DT[2], Months[DT[1]-1], DT[0], DT[4], DT[5], DT[6])

def PackWStr(AStr):
  bstr = AStr.encode('utf-8')
  return struct.pack('<H', len(bstr)) + bstr 

def FreeSpace():
  fs_info = os.statvfs('/')
  return (fs_info[0] * fs_info[3]) - 4096  

def SplitFileName(path):
  I = path.rfind('/')
  if I == -1: return '', path
  else: return path[:I+1], path[I+1:]

def I2CExists(TheI2C, Addr):
  devices = TheI2C.scan()
  return Addr in devices

def UpdateUptime():
  global Uptime, UTLastTicks  
  NowTicks = time.ticks_ms() 
  tkDiff = time.ticks_diff(NowTicks, UTLastTicks)
  UTLastTicks = NowTicks
  Uptime[4] += tkDiff
  rest, Uptime[4] = divmod(Uptime[4], 1000)
  Uptime[3] += rest
  rest, Uptime[3] = divmod(Uptime[3], 60)
  Uptime[2] += rest
  rest, Uptime[2] = divmod(Uptime[2], 60)
  Uptime[1] += rest
  rest, Uptime[1] = divmod(Uptime[1], 24)
  Uptime[0] += rest  

def LogMsg(FileName, Msg): 
  try:
    with open(FileName, 'a') as fText:
      DT = time.localtime(time.time())
      TimeSt = '{:02d}-{:02d}-{:04d}, {:02d}:{:02d}:{:02d} : '.format(DT[2], DT[1], DT[0], DT[3], DT[4], DT[5])  
      fText.write(TimeSt+Msg+'\n')
  except: pass


def ExtractFileVer(fname):
  SM = b'$version$:'; EM = ord(':'); NV = '---'
  try:
    with open(fname, 'rb') as f:
      while True:
        data = f.read(512); f.seek(-24, 1)
        if not data: return NV
        idx = data.find(SM)
        if idx == -1: continue 
        VS = idx + len(SM); VE = VS
        while VE < len(data) and data[VE] != EM: VE += 1
        if VE >= len(data): continue
        return data[VS:VE].decode()
  except: return NV

def PackStatus():
  gc.collect(); mfree = gc.mem_free(); msize = mfree + gc.mem_alloc()
  fs_info = os.statvfs('/'); fs_size = fs_info[1] * fs_info[2]; fs_free = fs_info[0] * fs_info[3]
  mem_days, disk_days = WData.StoredDays
  machine = sys.implementation._machine
  firmware = f'Python v{sys.version}'
  sys_pltf = platform.platform()
  UpdateUptime(); DT = PicoRTC.datetime()
  Sdevs = SensI2C.scan(); Pdevs = PowerI2C.scan()
  data = struct.pack('<IIII', mfree, msize, fs_free, fs_size)                             # RAM & Flash info
  data += struct.pack('<HHHH', Uptime[0], Uptime[1], Uptime[2], Uptime[3])                # Uptime
  data += struct.pack('<HHHHHHB', DT[0], DT[1], DT[2], DT[4], DT[5], DT[6], ClockSynced)  # Current datetime
  data += struct.pack('<HHB', mem_days, disk_days, WData.Synced)                          # Database status 
  data += struct.pack('<B', len(Sdevs)) + bytes(Sdevs)                                    # Sens I2C devices
  data += struct.pack('<B', len(Pdevs)) + bytes(Pdevs)                                    # Power I2C devices
  data += PackWStr(machine) + PackWStr(firmware) + PackWStr(sys_pltf) \
   + PackWStr(ScriptVer[10:-1]) + PackWStr(ExtractFileVer(MainProj))
  return data


def MakeCMD(CmdCode):
  bins = bytearray(CmdCode)
  bins[1] = PICO_CMDID
  return bytes(bins) 

def FromComp(CmdCode):
  bins = bytearray(CmdCode)
  return (bins[1] == COMP_CMDID)

def GetCMD(CmdCode):
  bins = bytearray(CmdCode)
  bins[1] = 0x00
  return bytes(bins)    


def PicoPath(WinPath):
  if ':\\' in WinPath:
    drive, rest = WinPath.split(':\\', 1)
    rest = rest.replace('\\', '/')  
    return drive+':', '/'+rest
  else:
    return None, WinPath.replace('\\', '/')

def WinPath(Drive, PicoPath):
  Path = PicoPath.replace('/', '\\')
  if Drive == None: return Path
  else: return Drive + Path    

def JoinPath(path, file):
  if path.endswith('/'): return path + file
  else: return path + '/' + file

def LastPathItem(path):
  if path.endswith('/'): path = path[:-1]  
  res = path.rsplit('/', 1)
  return res[1] if len(res) > 1 else res[0]

def PathExists(Path, IncFiles=False):
  if Path == '': return False
  try:
    stat = os.stat(Path)
    return True if IncFiles or (stat[0] & 0o170000 == 0o040000) else False
  except: return False

def SilentRemove(path, isdir = False):
  try: 
    if isdir: os.rmdir(path)
    else: os.remove(path)
  except: pass

def ValidatePath(Path, TryMakeIt=False, IncFiles=False):  # only for absolute paths
  if not Path.startswith('/'): return False, Path
  while len(Path) >= 2:
    if PathExists(Path, IncFiles): return True, Path
    if TryMakeIt: Path = Path.rsplit('/', 1)[0]
    else: return False, Path
  return True, '/'        

def ListDir(path):
  try:
    result = []
    entries = os.listdir(path)
    fpath = path if path.endswith('/') else path+'/'
    for entry in entries:
      full_path = fpath + entry
      stat = os.stat(full_path)
      if stat[0] & 0o170000 == 0o040000:
        result.append((True, entry))
      else:
        size = stat[6] 
        mtime = stat[8] 
        result.append((False, entry, size, mtime))
    return result
  except: return None
  
def DriveInfo():
  try:
    fs_info = os.statvfs('/')
    fs_size = fs_info[1] * fs_info[2]
    fs_free = fs_info[0] * fs_info[3]
    return (fs_size, fs_free, 'LFS')
  except: return None

def PackPathQuery(Path, MakeValid, IncFiles, GetPack, GetCDI):  # Path = Windows path format
  if Path.endswith(':'): Path += '\\'
  Drive, Path = PicoPath(Path)
  PathValid, Path = ValidatePath(Path, MakeValid, IncFiles)
  if PathValid:
    PathPack = ListDir(Path) if GetPack else None
    CDIPack = DriveInfo() if GetCDI else None
  Path = WinPath(Drive, Path)
  Buff = struct.pack('<B', PathValid)
  if Path.endswith(':\\'): Path = Path[:-1]
  if PathValid:
    Buff += PackWStr(Path) + struct.pack('<B', PathPack != None)
    if PathPack != None:
      Buff += struct.pack('<I', len(PathPack))
      for Item in PathPack:
        Buff += struct.pack('<B', Item[0]) + PackWStr(Item[1])
        if not Item[0]:
          DT = time.localtime(Item[3])  
          Buff += struct.pack('<iHHHHHH', Item[2], DT[0], DT[1], DT[2], DT[3], DT[4], DT[5])  
    Buff += struct.pack('<B', CDIPack != None)
    if CDIPack != None:
      Buff += struct.pack('<QQ', CDIPack[0], CDIPack[1]) + PackWStr(CDIPack[2])
  return Buff  

def BackupExists(path='/'):
  try:
    items = os.listdir(path)
    if not path.endswith('/'): path += '/'
    for item in items:
      if os.stat(path+item)[0] & 0o170000 != 0o040000:
        if item.endswith('.bak'): return True
      else:
        if BackupExists(path+item): return True
    return False
  except: return False

def RestoreBackup(path='/'):
  restored = False  
  try:
    items = os.listdir(path)
    if not path.endswith('/'): path += '/'
    for item in items:
      ipath = path + item  
      if os.stat(ipath)[0] & 0o170000 != 0o040000:
        if ipath.endswith('.bak'):
          os.rename(ipath, ipath[:-4])
          restored = True
      else:
        if RestoreBackup(path+item): restored = True
    return restored
  except: return restored

def RemoveBackup(path='/'):
  try:
    items = os.listdir(path)
    if not path.endswith('/'): path += '/'
    for item in items:
      if os.stat(path+item)[0] & 0o170000 != 0o040000:
        if item.endswith('.bak'): os.remove(path+item)
      else: RemoveBackup(path+item)
  except: pass


def StorePower(LmV, LmA, BmV, BmA, Tdeg):
  global Sidx
  LVBuff[Sidx:Sidx+2] = struct.pack('<H', round(LmV))
  LIBuff[Sidx:Sidx+2] = struct.pack('<H', round(LmA))
  BVBuff[Sidx:Sidx+2] = struct.pack('<H', round(BmV))
  BIBuff[Sidx:Sidx+2] = struct.pack('<h', round(BmA))
  BTBuff[Sidx:Sidx+2] = struct.pack('<h', round(Tdeg*100))
  Sidx += 2 
  if Sidx >= LDBSize: Sidx = 0

def SavePowerData():
  try:
    if not ClockSynced: os.remove(PowerFile)
    else:
      NT = PicoRTC.datetime()
      HeadData = struct.pack('<HHHHHH', Sidx, NT[0], NT[1], NT[2], NT[4], NT[5])
      with open(PowerFile, 'wb') as fPower:
        fPower.write(HeadData)
        fPower.write(LVBuff); fPower.write(LIBuff)
        fPower.write(BVBuff); fPower.write(BIBuff)
        fPower.write(BTBuff)
  except: pass  

def LoadPowerData():
  def RestoreBuff(TheBuff):
    data = fPower.read(LDBSize)
    data = data[Gidx:]+data[:Gidx]
    TheBuff[Sidx:Sidx+size] = data[-size:] 
    I = Sidx+size-2; LastValue = TheBuff[I:I+2]
    for I in range(I+2, LDBSize, 2): TheBuff[I:I+2] = LastValue
  fPower = None
  try:
    fPower = open(PowerFile, 'rb')
    Head = struct.unpack('<HHHHHH', fPower.read(12))
    Gidx = Head[0]
    NT = PicoRTC.datetime()
    NTS = time.mktime((NT[0], NT[1], NT[2], NT[4], NT[5], 0, 0, 0))
    GTS = time.mktime((Head[1], Head[2], Head[3], Head[4], Head[5], 0, 0, 0))
    diff = (NTS - GTS) // 30  # min * 2 bytes
    if (diff < 0) or (diff >= LDBSize): return
    size = LDBSize - diff
    RestoreBuff(LVBuff); gc.collect()
    RestoreBuff(LIBuff); gc.collect()
    RestoreBuff(BVBuff); gc.collect() 
    RestoreBuff(BIBuff); gc.collect()
    RestoreBuff(BTBuff); gc.collect()
    fPower.close(); fPower = None
    if not Debug: os.remove(PowerFile)
  except: pass 
  finally:
    if fPower != None: fPower.close()


def GetWeatherBME():
  global BmeReady
  try:
    if not BmeReady: return 0, 0, 100000, 0 
    temp, hum, press = BMESens.Values
    dew = BMESens.CalcDewPoint(temp, hum)
    return temp, hum, press, dew
  except Exception as E:
    BmeReady = False
    return 0, 0, 100000, 0 

def GetWeatherAHT():
  global AhtReady
  try:
    if not AhtReady: return 0, 0, 0
    temp, hum = AHTSens.ReadTH()
    dew = AHTSens.CalcDewPoint(temp, hum)
    return temp, hum, dew
  except Exception as E:
    AhtReady = False
    return 0, 0, 0 

def InitSensors(doReset=False):
  global BMESens, BmeReady, AHTSens, AhtReady    
  BMESens = None; AHTSens = None; gc.collect()
  AhtReady = I2CExists(SensI2C, AhtAddr)
  if AhtReady: AHTSens = Devices.AHT25(SensI2C, AhtAddr, reset=doReset)
  BmeReady = I2CExists(SensI2C, BmeAddr)
  if BmeReady: BMESens = Devices.BME280(SensI2C, BmeAddr, mode=Devices.MODE_NORMAL, standby=Devices.STDBY_250m,
    filters=Devices.FILTER_8, osrs=Devices.OSAMPLE_4, reset=doReset)


def GetDisRI():
  try:
    VBIdle = (VRef + BatADC.GetChannel(Devices.DIF23)) * BDivR  # battery idle voltage (mV)
    LoadEn.value(1); time.sleep_ms(50)
    VBLoad = (VRef + BatADC.GetResult()) * BDivR  # battery voltage under load (mV)
    VRTest = BatADC.GetChannel(Devices.AIN1)
    LoadEn.value(0)
    BatADC.SetConfig(Devices.DIF23)     
    ITest  = VRTest / RTest    # test current (mA)
    Vdrop = ITest * (RBplus + RBminus)   # additional voltage drop in circuit (mV)
    VBLoad += Vdrop            # real battery voltage under load (mV)
    VRI = VBIdle - VBLoad      # voltage drop across battery internal resistance (mV)
    RI = (VRI / ITest) * 1000  # battery internal resistance (mΩ)
    return RI, VRI, ITest
  finally:
    LoadEn.value(0)  

def GetChgRI():
  try:
    VBIdle = (VRef + BatADC.GetChannel(Devices.DIF23)) * BDivR  # battery idle voltage (mV)
    ChgEn.value(1); time.sleep_ms(160)
    VBLoad = (VRef + BatADC.GetResult()) * BDivR  # battery voltage under load (mV)
    ITest = BatADC.GetChannel(Devices.AIN0) * BIconst  # test current (mA)
    ChgEn.value(0)
    BatADC.SetConfig(Devices.DIF23)     
    Vdrop = ITest * RBminus    # additional voltage drop in circuit (mV)
    VBLoad -= Vdrop            # real battery voltage under load (mV)
    VRI = VBLoad - VBIdle      # voltage drop across battery internal resistance (mV)
    RI = (VRI / ITest) * 1000  # battery internal resistance (mΩ)
    return RI, VRI, ITest
  finally:
    ChgEn.value(0)  


def BatAvgTemp(last_mins):
  LMB = min(int(last_mins) * 2, LDBSize)
  data = BTBuff[Sidx:]+BTBuff[:Sidx]
  All = 0; Count = 0;
  for idx in range(LDBSize-LMB, LDBSize, 2):
    Value = struct.unpack('<h', data[idx:idx+2])[0]
    if Value != -32768:
      All += Value/100; Count += 1  
  if Count == 0: return None
  else: return All / Count

def BatSelfDischg(time_hours, temperature):
  time_months = time_hours/720  
  if temperature >= 20:
    # Original linear model for T >= 20°C
    capacity_loss = ((0.7 * temperature - 6) / 3) * time_months
  else:
    # Adjusted linear model for T < 20°C. Ensure capacity loss decreases smoothly 
    base_loss = ((0.7 * 20 - 6) / 3) * time_months  # Loss at 20°C
    scaling_factor = (temperature + 20) / 40  # Scales loss down to 0 at -20°C
    capacity_loss = base_loss * scaling_factor
  # Ensure capacity loss is never negative
  capacity_loss = max(capacity_loss, 0)
  return (BRatedCap / 100) * capacity_loss

def BatSDComp(AvgTemp=None):
  global HoldCap, SelfDisTS, tkSelfDis
  tkNow = time.ticks_ms()    
  NowTS = time.time()
  SPassed = NowTS - SelfDisTS
  MPassed = SPassed // 60
  HPassed = SPassed / 3600
  if AvgTemp == None: 
    AvgTemp = BatAvgTemp(MPassed)
  if AvgTemp != None:
    LosedCap = BatSelfDischg(HPassed, AvgTemp)
    HoldCap -= LosedCap
    SelfDisTS = NowTS; tkSelfDis = tkNow
    if Debug: print(f'Self discharge: PM = {MPassed} / TAVG = {AvgTemp} / Losed = {LosedCap} mAh')  


async def SyncRTC(forced=False):
  global ClockSynced
  try:
    ntptime.settime()
    ltime  = time.gmtime(time.time() + (TMZ_OFFSET * 3600))
    ltuple = (ltime[0], ltime[1], ltime[2], ltime[6], ltime[3], ltime[4], ltime[5], 0)
    PicoRTC.datetime(ltuple)
    if forced or (time.time() >= LastRTC):
      ClockSynced = True; CSync.value(1)
      if Debug: print('Clock synced: '+TimeStr())
      return False
    else:
      # buzzer alarm... ?  
      if Debug: print(MsgClockBack)
      return True
  except Exception as E: 
    LogException('Clock Sync Error', E)
    return False

async def OnClockSynced():
  global SelfDisTS, tkSelfDis
  UpdateNetLed()
  async with fsLock: 
    WData.SyncBuffers()
    async with pdLock: LoadPowerData()
  if (FullCap > 0) and (SelfDisTS == 0): 
    SelfDisTS = time.time()
    tkSelfDis = time.ticks_ms()
  else: BatSDComp(BTmpADC.Temperature())
  gc.collect()


def UpdateStatLed():
  rp2.StateMachine(0).active(0)  
  if Terminated:
    Pin(pinLedGrn, Pin.OUT, value=1)
    if not Fault: Pin(pinLedRed, Pin.OUT, value=1)
    else: rp2.StateMachine(0, blink_1hz, freq=2000, set_base=Pin(pinLedRed)).active(1)
  elif OnBattery:
    Pin(pinLedRed, Pin.OUT, value=1)
    rp2.StateMachine(0, blink_1hz, freq=2000, set_base=Pin(pinLedGrn)).active(1)
  elif Charging:
    Pin(pinLedGrn, Pin.OUT, value=1)
    Pin(pinLedRed, Pin.OUT, value=0)
  else:  
    Pin(pinLedRed, Pin.OUT, value=1)
    Pin(pinLedGrn, Pin.OUT, value=0)

def UpdateNetLed(wConn=None):
  if wConn == None: wConn = wlan.isconnected()
  if not wConn:
    rp2.StateMachine(1).active(0)  
    Pin(pinNetLed, Pin.OUT, value=0)
  elif ClockSynced:
    rp2.StateMachine(1).active(0)  
    Pin(pinNetLed, Pin.OUT, value=1)
  else:
    rp2.StateMachine(1, blink_1hz, freq=6000, set_base=Pin(pinNetLed)).active(1)  


# ------ Network functions ------------------

async def NetReadEx(reader, size, tmout=3):
  data = b''
  while len(data) < size:
    chunk = await asyncio.wait_for(reader.read(size - len(data)), tmout)
    if not chunk: raise IncompleteData()
    data += chunk
  return data

async def NetReadLineEx(reader, tmout=3):
  return await asyncio.wait_for(reader.readline(), tmout) 

async def NetWriteEx(writer, buff, tmout=3):
  writer.write(buff)
  await asyncio.wait_for(writer.drain(), tmout) 

async def NetWriteBuffEx(writer, buff, tmout=3):
  mvBuff = memoryview(buff)
  for I in range(0, len(mvBuff), nbSize):
    writer.write(mvBuff[I:I+nbSize]) 
    await asyncio.wait_for(writer.drain(), tmout) 


async def SendCmdBuff(CMD, Buff, Name='SendCmdBuff'):
  global SendRTI, RTIF
  if not wlan.isconnected() or (CompIP == 'none'): return False
  writer = None; Success = False
  try:
    reader, writer = await asyncio.open_connection(CompIP, CompPort)  
    await NetWriteEx(writer, MakeCMD(CMD) + struct.pack('<I', len(Buff)))
    await NetWriteBuffEx(writer, Buff)
    Success = await NetReadEx(reader, 4) == CMD_ACKN
    return Success
  except (asyncio.TimeoutError, IncompleteData): return False   
  except OSError as E:
    if (E.errno != 104) and (E.errno != 12): LogException(ErrorCmdBuff+Name, E); return False  
  except Exception as E: LogException(ErrorCmdBuff+Name, E); return False
  finally:
    if (CMD == CMD_POWER) or (CMD == CMD_WEATHER):
      if Success: RTIF = 0
      else: RTIF += 1
      if RTIF >= 3: SendRTI = False
    if writer != None: writer.close(); await writer.wait_closed()

async def SendMessage(msg, color=clNorm):
  if Debug: print(msg)
  Buff = struct.pack('<B', color) + PackWStr(msg)
  return await SendCmdBuff(CMD_MESSAGE, Buff, 'SendMessage')  

async def SendExceptLog():
  if not wlan.isconnected() or (CompIP == 'none'): return False
  writer = None
  try:
    async with fsLock:
      try: fsize = os.stat(ExceptFile)[6]
      except: fsize = 0
      reader, writer = await asyncio.open_connection(CompIP, CompPort)  
      await NetWriteEx(writer, MakeCMD(CMD_EXCEPT) + struct.pack('<I', fsize))
      if fsize > 0:
        with open(ExceptFile, 'rb') as fData:
          while True:
            buff = fData.read(nbSize)
            if not buff: break
            await NetWriteEx(writer, buff)
    return await NetReadEx(reader, 4) == CMD_ACKN
  except (asyncio.TimeoutError, IncompleteData): return False   
  except OSError as E:
    if E.errno != 104: LogException(ErrorExLog, E); return False  
  except Exception as E: LogException(ErrorExLog, E); return False
  finally:
    if writer != None: writer.close(); await writer.wait_closed()  

async def SendMemoryMap():
  if not wlan.isconnected() or (CompIP == 'none'): return False
  writer = None
  try:
    import mem_info
    gc.collect()
    addr, bsize = mem_info.snapshot()
    maxfree = mem_info.max_free() * 16
    mfree = gc.mem_free(); msize = mfree + gc.mem_alloc()
    mem_map = uctypes.bytearray_at(addr, bsize)
    reader, writer = await asyncio.open_connection(CompIP, CompPort)  
    await NetWriteEx(writer, MakeCMD(CMD_MEMORY) + struct.pack('<IIIIH', 14 + bsize, msize, mfree, maxfree, bsize))
    await NetWriteBuffEx(writer, mem_map)
    Success = await NetReadEx(reader, 4) == CMD_ACKN
    return Success
  except (asyncio.TimeoutError, IncompleteData): return False   
  except OSError as E:
    if E.errno != 104: LogException(ErrorMemMap, E); return False  
  except Exception as E: LogException(ErrorMemMap, E); return False
  finally:
    if writer != None: writer.close(); await writer.wait_closed()  

async def SendLDBuffs(ldID):
  if not wlan.isconnected() or (CompIP == 'none') or not (ldID in [ldLVI, ldBVI, ldBT]): return False
  writer = None
  try:
    reader, writer = await asyncio.open_connection(CompIP, CompPort)
    if ldID == ldLVI:
      await NetWriteEx(writer, MakeCMD(CMD_LOADVI) + struct.pack('<I', len(LVBuff) + len(LIBuff) + 2))
      await NetWriteBuffEx(writer, LVBuff); await NetWriteBuffEx(writer, LIBuff)
    elif ldID == ldBVI:
      await NetWriteEx(writer, MakeCMD(CMD_BATVI) + struct.pack('<I', len(BVBuff) + len(BIBuff) + 2))
      await NetWriteBuffEx(writer, BVBuff); await NetWriteBuffEx(writer, BIBuff)
    elif ldID == ldBT:
      await NetWriteEx(writer, MakeCMD(CMD_BATTEMP) + struct.pack('<I', len(BTBuff) + 2))
      await NetWriteBuffEx(writer, BTBuff)
    await NetWriteEx(writer, struct.pack('<H', Sidx))
    return await NetReadEx(reader, 4) == CMD_ACKN
  except (asyncio.TimeoutError, IncompleteData): return False   
  except OSError as E:
    if E.errno != 104: LogException(ErrorLDBuff, E); return False  
  except Exception as E: LogException(ErrorLDBuff, E); return False
  finally:
    if writer != None: writer.close(); await writer.wait_closed()    

async def UploadWeatherDay():
  if not wlan.isconnected() or (CompIP == 'none'): return False
  writer = None
  try:
    reader, writer = await asyncio.open_connection(CompIP, CompPort)  
    await NetWriteEx(writer, MakeCMD(CMD_SENDWDAY))
    if await NetReadEx(reader, 4) != CMD_ACKN: return False
    await NetWriteEx(writer, struct.pack('<HHH', WData.BDate[0], WData.BDate[1], WData.BDate[2]))
    for buff in WData.Buffers: await NetWriteBuffEx(writer, buff)
    return await NetReadEx(reader, 4) == CMD_ACKN
  except (asyncio.TimeoutError, IncompleteData): return False   
  except OSError as E:
    if E.errno != 104: LogException(ErrorWDayUpload, E); return False  
  except Exception as E: LogException(ErrorWDayUpload, E); return False
  finally:
    if writer != None: writer.close(); await writer.wait_closed()  

async def CompAppVis():
  if not wlan.isconnected() or (CompIP == 'none'): return False
  writer = None
  try:
    reader, writer = await asyncio.open_connection(CompIP, CompPort)  
    await NetWriteEx(writer, MakeCMD(CMD_VISIBLE), tmout=1)
    data = await NetReadEx(reader, 1, tmout=1) 
    IsVisible = bool(data[0])
    await NetWriteEx(writer, b'\x00', tmout=1)
    return IsVisible
  except: return False
  finally:
    if writer != None: writer.close(); await writer.wait_closed()   


# ------ PIO Blinker -------------------------

@rp2.asm_pio(set_init=rp2.PIO.OUT_HIGH)
def blink_1hz():
  # Cycles: 1 + 7 + 32 * (30 + 1) = 1000
  set(pins, 1)
  set(x, 31)                  [6]
  label("delay_high")
  nop()                       [29]
  jmp(x_dec, "delay_high")
  # Cycles: 1 + 7 + 32 * (30 + 1) = 1000
  set(pins, 0)
  set(x, 31)                  [6]
  label("delay_low")
  nop()                       [29]
  jmp(x_dec, "delay_low")    


# ------ Interrupt Service Routines ----------

def ShutdownISR(pin):
  AsyncAddCmd(tcShutdown)

def ChgStatISR(pin):
  AsyncAddCmd(tcChgStat)
  

# ------ Power Task ---------------------------

async def PowerTask():
  global OnBattery, ChgStartReq, ChgStopReq, FullCap, HoldCap, SelfDisTS, tkSelfDis

  async def StartCharger():
    global BChgSV, TChgSL, TChgSH
    nonlocal ChgStarted, WasCharged
    ChgEn.value(1); ChgStarted = True
    TChgSL = TChgL; TChgSH = TChgH; BChgSV = ChgVStop 
    WasCharged = False
    await SendMessage(MsgStartChg)

  async def StopCharger(reason=srNone):
    global BChgSV, TChgSL, TChgSH
    nonlocal ChgStarted
    ChgEn.value(0); ChgStarted = False
    if reason == srDone: TChgSL = TChgL; TChgSH = TChgH; BChgSV = ChgVStart
    elif reason == srTemp: TChgSL = TChgL + BTHyst; TChgSH = TChgH - BTHyst
    await SendMessage(MsgStopChg)

  def MarkEmpty():
    global FullCap, HoldCap
    FullCap -= HoldCap
    HoldCap = 0.0 

  def MarkFull():
    global FullCap
    FullCap = HoldCap 

  #  0         700 mAh                        2700 mAh   3200 mAh
  #  [-----------][======================........][---------]       Battery SoC
  #              0 %                   80 %     100 %       

  TaskEnter('PowerTask')  
  try:
    ChgStarted = False; LastChg = False; LastOnBat = False; WasCharged = False
    Coulomb = 0; Energy = 0; CompRI = 0; VBComp = 0
    tkNow = time.ticks_ms(); tkStorePwr = tkNow; tkSelfDis = tkNow
    while not Terminated:
      VLoad = (VRef + LoadADC.GetResult()) * LDivR        # mV
      ILoad = LoadADC.GetChannel(Devices.AIN0) * LIconst  # mA
      PLoad = (VLoad * ILoad) / 1000                      # mW
      LoadADC.SetConfig(Devices.DIF23, delay=False) 
      VBRaw = (VRef + BatADC.GetResult()) * BDivR         # mV
      IChg  = BatADC.GetChannel(Devices.AIN0) * BIconst   # mA
      BatADC.SetConfig(Devices.DIF23, delay=False) 
      BatTemp = BTmpADC.Temperature()                     # °C 

      OnBattery = VLoad < (VBRaw + 20)
      if OnBattery: IBat = -ILoad                         # mA 
      elif Charging: IBat = IChg                          # mA 
      else: IBat = 0                                      # mA 
      VBat = VBRaw - (RBminus * IBat)                     # mV
      VBComp = VBat                                       # mV 
      if SendRTI or Charging or OnBattery: 
        CompRI = BatRI * BCRatio(BatTemp)                 # mΩ

      dtChg = IBat / 1800                                 # mAh 
      if (Coulomb > 0) and (dtChg <= 0):    # exit charging
        EnStr = f'{Energy/1000:.3f} Wh' if Energy >= 1000 else f'{Energy:.2f} mWh'
        msg = f'Battery charge increased by {Coulomb:.2f} mAh. Energy used: {EnStr}'
        if Debug: print(msg)
        await SendMessage(msg)
        Coulomb = 0; Energy = 0
      elif (Coulomb < 0) and (dtChg >= 0):  # exit discharging
        EnStr = f'{abs(Energy/1000):.3f} Wh' if Energy <= -1000 else f'{abs(Energy):.2f} mWh'
        msg = f'Battery charge decreased by {abs(Coulomb):.2f} mAh. Energy used: {EnStr}'
        await SendMessage(msg)
        Coulomb = 0; Energy = 0  
      if dtChg > 0:
        Coulomb += dtChg                                  # mAh
        Energy  += dtChg * VBRaw / 1000                   # mWh
      elif dtChg < 0:
        Coulomb += dtChg                                  # mAh
        Energy  += dtChg * VLoad / 1000                   # mWh  
      if FullCap > 0:  
        HoldCap += dtChg
        if HoldCap > FullCap: MarkFull() 
        if HoldCap < 0: MarkEmpty()

      OnBatJS = OnBattery != LastOnBat
      ChgJS = Charging != LastChg

      if OnBatJS:  # Did Bat source just switched ?
        LastOnBat = OnBattery
        UpdateStatLed() 
        if OnBattery: await SendMessage(MsgPowerLost, clWarn)
        else: await SendMessage(MsgPowerAvail)

      if ChgJS:  # Did Charger just switched ?
        LastChg = Charging
        if Charging: WasCharged = True

      if ChgStarted and (not ChargerEn or ChgStopReq or OnBattery):
        await StopCharger(int(not ChargerEn or ChgStopReq))

      if OnBattery:   #--- Discharging ---------
        VBComp -= (IBat * CompRI / 1000)                  # mV
        if VBComp <= BatVOff:
          MarkEmpty()
          TerminateProgram()
        if not (TDisL < BatTemp < TDisH):
          await SendMessage(MsgBatTemp+f'{BatTemp} °C', clWarn)
          TerminateProgram()
      else:           #--- Charging or Idle ---- 
        if ChgStarted:
          if Charging: VBComp -= (IBat * CompRI / 1000)   # mV
          if (VBComp >= ChgVStop) or (WasCharged and (IBat < ChgIEnd)): 
            MarkFull(); await StopCharger(srDone)
          if not (TChgL < BatTemp < TChgH):
            await SendMessage(MsgBatTemp+f'{BatTemp} °C', clCrit)
            if ChgStarted: await StopCharger(srTemp)
        else:  
          if ChargerEn and not ChgStopReq and (ChgStartReq or (VBComp <= BChgSV)) \
            and (TChgSL < BatTemp < TChgSH): await StartCharger()

      tkNow = time.ticks_ms()
      if time.ticks_diff(tkNow, tkStorePwr) >= 60000:
        async with pdLock: StorePower(VLoad, ILoad, VBat, IBat, BatTemp); 
        tkStorePwr = time.ticks_add(tkStorePwr, 60000)
      if ClockSynced and (FullCap > 0) and (SelfDisTS > 0) and (time.ticks_diff(tkNow, tkSelfDis) >= 3600000): BatSDComp()

      if SendRTI:
        Buff = struct.pack('<HHHBHhhHHiiffh', round(VLoad), round(ILoad), round(PLoad),
          OnBattery, round(VBat), round(IBat), round(BatTemp*100), BatRI, round(VBComp),
          round(Coulomb*100), round(Energy*100), round(FullCap, 3), round(HoldCap, 3), wlan.status('rssi'))
        await SendCmdBuff(CMD_POWER, Buff, 'Power RTI')

      ChgStartReq = False; ChgStopReq = False
      try: await asyncio.wait_for(waitPower.wait(), 2)
      except asyncio.TimeoutError: pass
      waitPower.clear()
  except asyncio.CancelledError: pass
  finally: TaskExit('PowerTask')


# ------ Sensors Task ---------------------------

async def SensorsTask():
  global Wtemp, Whum, Wpres, Wdew, tkSensInit
  TaskEnter('SensorsTask')  
  try:
    while not Terminated:

      if not BmeReady:
        tkNow = time.ticks_ms()
        if time.ticks_diff(tkNow, tkSensInit) >= 30000:  # try to init sensors at ~30 seconds interval
          tkSensInit = tkNow
          InitSensors(doReset=True)

      Wtemp, Whum, Wpres, Wdew = GetWeatherBME()

      if WData.Ready:
        LastOne = WData.LastSample
        WData.AddSample(round(Wtemp*100), round(Whum*100), round(Wpres)-60000)
        if LastOne:
          isStored = await UploadWeatherDay()
          async with fsLock: WData.CloseDay(isStored)

      if Whum > 90:
        pass  # give dew warning 

      if SendRTI:
        Atemp, Ahum, Adew = GetWeatherAHT()
        Buff = struct.pack('<hHIhfff', round(Wtemp*100), round(Whum*100), round(Wpres), round(Wdew*100), Atemp, Ahum, Adew)
        await SendCmdBuff(CMD_WEATHER, Buff, 'Weather RTI')

      try: await asyncio.wait_for(waitSens.wait(), 6)
      except asyncio.TimeoutError: pass
      waitSens.clear()
  except asyncio.CancelledError: pass
  finally: TaskExit('SensorsTask')


# ------ WiFi Network Task -------------------

async def HandleClient(reader, writer):
  global SendRTI, ChgStartReq, ChgStopReq, ChargerEn, BatRI, CompIP, CompPort, ReqPort
  global FullCap, HoldCap, SelfDisTS, tkSelfDis, ChgVStart, ChgVStop, ChgIEnd, BatVOff, BChgSV
  global TChgL, TChgH, TDisL, TDisH, TChgSL, TChgSH

  async def ReadWStr(tmout=3):
    buff = await NetReadEx(reader, 2, tmout)
    size = struct.unpack('<H', buff)[0]
    if size == 0: return ''
    buff = await NetReadEx(reader, size, tmout)
    return buff.decode('utf-8')  

  async def ForResult(CmdBuff=None):
    if CmdBuff != None: await NetWriteBuffEx(writer, CmdBuff)
    Rpl = await NetReadEx(reader, 2)
    if Rpl == SC_ACKN: return
    if Rpl == SC_FAIL: await NetWriteEx(writer, SC_ACKN)
    raise AbortWork()

  async def EndWithError(errMsg, errItem=None):
    if errItem != None: errMsg += f' "{WinPath(wDrv, errItem)}"'
    await NetWriteEx(writer, SC_FAIL + PackWStr(errMsg))
    await NetReadEx(reader, 2)
    raise AbortWork()

  async def EndAcknError():
    await NetWriteEx(writer, SC_ACKN)
    raise AbortWork()      

  async def SendFiles(dirpath, flist, move):
    if not dirpath.endswith('/'): dirpath += '/'   
    for item in flist:
      if isinstance(item, tuple): ritem = item[0]; witem = item[1]
      else: ritem = item; witem = item  
      ipath = dirpath + ritem
      try: 
        stat = os.stat(ipath)
        fsize = stat[6]
        isFolder = stat[0] & 0o170000 == 0o040000
      except: await EndWithError(ErrorNoPath, ipath)
      if not isFolder: # --- Send File ---
        try: fData = open(ipath, 'rb')
        except: await EndWithError(ErrorOpenFile, ipath)
        try:  
          await ForResult(SC_FILE + PackWStr(witem) + struct.pack('<i', fsize))
          sha256 = hashlib.sha256()
          while True:
            try: rBuff = fData.read(nbSize)
            except: EndWithError(ErrorReadFile, ipath)
            if not rBuff: break
            sha256.update(rBuff)
            await NetWriteEx(writer, struct.pack('>H', len(rBuff)))
            await ForResult(rBuff)
            await asyncio.sleep(0)
          await ForResult(SC_SHA2 + sha256.digest())
        finally: fData.close()      
        if move and (ipath != ExceptFile): SilentRemove(ipath)
      else:  # --- Send Folder ---
        try: nlist = os.listdir(ipath)
        except: await EndWithError(ErrorListDir, ipath)
        await ForResult(SC_DIR + PackWStr(witem))
        await SendFiles(ipath, nlist, move)
        if move: SilentRemove(ipath, True)
    await ForResult(SC_RET) 

  async def RecvFiles(DestPath, keepBack):
    if Files.MakeFolders(DestPath): await NetWriteEx(writer, SC_ACKN)
    else: await EndWithError(ErrorMakePath, DestPath)
    Level = 0  
    while True:
      FCMD = await NetReadEx(reader, 2)
      if FCMD == SC_FILE:
        fname = await ReadWStr(); ipath = JoinPath(DestPath, fname)
        fsize = struct.unpack('<i', await NetReadEx(reader, 4))[0]
        doBack = ipath.endswith('.mpy') or ipath.endswith('.py'); WriteEN = ipath != ExceptFile
        wpath = ipath+'.tmp' if doBack and PathExists(ipath, True) else ipath
        if WriteEN: SilentRemove(wpath)
        if doBack: SilentRemove(ipath+'.bak')
        if fsize > FreeSpace(): await EndWithError(ErrorNoSpace, ipath)
        try: fData = open(wpath, 'wb') if WriteEN else None
        except: await EndWithError(ErrorCreateFile, ipath)
        doClose = True
        try:
          await NetWriteEx(writer, SC_ACKN)  
          sha256 = hashlib.sha256()
          while True:
            HB = await NetReadEx(reader, 2)
            if HB == SC_FAIL: await EndAcknError()
            if HB == SC_SHA2:
              if await NetReadEx(reader, 32) != sha256.digest(): await EndWithError(ErrorSHAFail, ipath)
              doClose = False
              try: 
                if WriteEN: fData.close()
              except: await EndWithError(ErrorCloseFile, ipath)
              if wpath != ipath:
                try: 
                  if keepBack: os.rename(ipath, ipath+'.bak')
                  else: os.remove(ipath)
                  os.rename(wpath, ipath)
                except: await EndWithError(ErrorRenBack, ipath)  
              await NetWriteEx(writer, SC_ACKN); break
            bsize = struct.unpack('<H', HB)[0]
            if bsize > 4096: raise AbortWork()
            wBuff = await NetReadEx(reader, bsize)
            try: 
              if WriteEN: fData.write(wBuff)
            except: await EndWithError(ErrorWriteFile, ipath)
            sha256.update(wBuff)  
            await NetWriteEx(writer, SC_ACKN)  
            await asyncio.sleep(0)
        except: 
          if WriteEN:
            if doClose: fData.close()
            os.remove(wpath)
          raise  
      elif FCMD == SC_DIR:
        DestPath = JoinPath(DestPath, await ReadWStr()); Level += 1
        if Files.MakeFolders(DestPath): await NetWriteEx(writer, SC_ACKN)
        else: await EndWithError(ErrorMakeDir, DestPath)
      elif FCMD == SC_RET:
        DestPath = Files.BackPath(DestPath) 
        await NetWriteEx(writer, SC_ACKN) 
        if Level <= 0: return
        else: Level -= 1 
      elif FCMD == SC_FAIL: await EndAcknError()
      else: raise AbortWork() 

  async def DeleteFiles(SrcPath, FList):
    if not SrcPath.endswith('/'): SrcPath += '/'
    for item in FList:
      ipath = SrcPath + item
      if (SrcPath == '/') and (ipath == ExceptFile):
        await ForResult(SC_DEL); continue
      try: isFolder = os.stat(ipath)[0] & 0o170000 == 0o040000
      except: await EndWithError(ErrNoPath, ipath)
      if not isFolder:
        try: os.remove(ipath)
        except: await EndWithError(ErrorRemFile, ipath)
        await ForResult(SC_DEL)
      else:
        try: nlist = os.listdir(ipath)
        except: await EndWithError(ErrorListDir, ipath)          
        await ForResult(SC_DIR + struct.pack('<I', len(nlist)))
        await DeleteFiles(ipath, nlist)
        try: os.rmdir(ipath)
        except: await EndWithError(ErrorRemDir, ipath)
        await ForResult(SC_DEL)
    await ForResult(SC_RET) 


  # ---------- Handler Start ---------------
  if Debug: print(MsgCliConn)
  try:
    CMD = await NetReadEx(reader, 4)
    if len(CMD) != 4: return
    if CMD == CMD_ALIVE:
      if Debug: print(f'Received CMD: [{CMD.hex()}]')
      await NetWriteEx(writer, CMD_ACKN)
      return
    if not FromComp(CMD): # and not FromAndro(CMD):
      if Debug: print(f'Received CMD: [{CMD.hex()}] from unknown source')
      return
    CMD = GetCMD(CMD)
    if Debug: print(f'Received CMD: [{CMD.hex()}]')   

    # -----------------------------------------

    if CMD == CMD_RTISTART: 
      await NetWriteEx(writer, CMD_ACKN)
      SendRTI = True; RTIF = 0 
      waitPower.set(); waitSens.set()  

    elif CMD == CMD_RTISTOP:
      await NetWriteEx(writer, CMD_ACKN)
      SendRTI = False

    elif CMD == CMD_LOADVI:  
      await NetWriteEx(writer, CMD_ACKN)
      async with pdLock: await SendLDBuffs(ldLVI)

    elif CMD == CMD_GETTODAY:
      if not WData.Synced: 
        await NetWriteEx(writer, CMD_NACK)
      else:  
        await NetWriteEx(writer, CMD_ACKN)
        await NetWriteEx(writer, struct.pack('<HHH', WData.BDate[0], WData.BDate[1], WData.BDate[2]))
        for buff in WData.Buffers: await NetWriteBuffEx(writer, buff)
      await NetReadEx(reader, 4)

    elif CMD == CMD_STATUS:
      await NetWriteEx(writer, CMD_ACKN)
      async with fsLock: buff = PackStatus()
      await SendCmdBuff(CMD_STATUS, buff, 'SendStatus')

    elif CMD == CMD_EXCEPT:       
      Clear = bool(struct.unpack('<B', await NetReadEx(reader, 1))[0])
      await NetWriteEx(writer, CMD_ACKN)
      if Clear: SilentRemove(ExceptFile)
      await SendExceptLog()

    elif CMD == CMD_RTCSYNC:
      forced = bool(struct.unpack('<B', await NetReadEx(reader, 1))[0])
      await NetWriteEx(writer, CMD_ACKN)
      if ClockSynced: await SendMessage(RTCAlSynced+TimeStr())
      else:
        wasSB = await SyncRTC(forced)
        if ClockSynced: 
          await OnClockSynced()
          await SendMessage(RTCSynced+TimeStr())
        else:
          if wasSB: await SendMessage(MsgClockBack, clWarn) 
          else: await SendMessage(MsgClkNotSync, clWarn)           

    elif CMD == CMD_SENSRESET:
      await NetWriteEx(writer, CMD_ACKN)
      InitSensors(doReset=True)       

    elif CMD == CMD_GETWDATA:
      await NetWriteEx(writer, CMD_ACKN)
      async with fsLock:
        try:
          for buff in WData.ReadData():
            if buff != None:
              await NetWriteEx(writer, SC_NEXT)
              await ForResult(buff)
              await asyncio.sleep(0)
            else:
              await ForResult(SC_DONE)
              WData.ReadDone(sync=ClockSynced)
        except:
          WData.ReadDone(False)

    elif CMD == CMD_MEMORY:
      await NetWriteEx(writer, CMD_ACKN)
      await SendMemoryMap()       

    elif CMD == CMD_SETNETW:  
      CompIP = await ReadWStr()
      CompPort, NewPPort = struct.unpack('<HH', await NetReadEx(reader, 4))
      await NetWriteEx(writer, CMD_ACKN)
      ReqPort = NewPPort; waitNetw.set()
      SendRTI = True; RTIF = 0 

    # ------- Battery Requests ------------

    elif CMD == CMD_CHGSTART: 
      await NetWriteEx(writer, CMD_ACKN)
      ChgStartReq = True

    elif CMD == CMD_CHGSTOP:
      await NetWriteEx(writer, CMD_ACKN)
      ChgStopReq = True  

    elif CMD == CMD_CHGENBL:
      ChargerEn = bool(struct.unpack('<B', await NetReadEx(reader, 1))[0])
      await NetWriteEx(writer, CMD_ACKN)

    elif CMD == CMD_BATVI:  
      await NetWriteEx(writer, CMD_ACKN)
      async with pdLock: await SendLDBuffs(ldBVI)

    elif CMD == CMD_BATTEMP:  
      await NetWriteEx(writer, CMD_ACKN)
      async with pdLock: await SendLDBuffs(ldBT)

    elif CMD == CMD_GETBINFO:
      await NetWriteEx(writer, CMD_ACKN)
      buff = struct.pack('<HHBHHHHffff', round(FullCap), round(HoldCap), ChargerEn, ChgVStart,
        ChgVStop, ChgIEnd, BatVOff, TChgL, TChgH, TDisL, TDisH)
      await SendCmdBuff(CMD_GETBINFO, buff, 'SendBatInfo');

    elif CMD == CMD_BSETCAP:
      buff = await NetReadEx(reader, 4)
      await NetWriteEx(writer, CMD_ACKN)
      Caps = struct.unpack('<HH', buff)
      FullCap = float(Caps[0])
      HoldCap = float(Caps[1]) if FullCap > 0 else 0
      if ClockSynced and (FullCap > 0):
        SelfDisTS = time.time(); tkSelfDis = time.ticks_ms()
      else: 
        SelfDisTS = 0; tkSelfDis = 0 

    elif CMD == CMD_BSETLVL:
      buff = await NetReadEx(reader, 8)
      await NetWriteEx(writer, CMD_ACKN)
      isStart = BChgSV == ChgVStart
      ChgVStart, ChgVStop, ChgIEnd, BatVOff = struct.unpack('<HHHH', buff)
      BChgSV = ChgVStart if isStart else ChgVStop

    elif CMD == CMD_BSETTMP:
      buff = await NetReadEx(reader, 16)
      await NetWriteEx(writer, CMD_ACKN)
      isFullRange = TChgSL == TChgL      
      Tmps = struct.unpack('<ffff', buff)
      TChgL = float(Tmps[0]); TChgH = float(Tmps[1])
      TDisL = float(Tmps[2]); TDisH = float(Tmps[3])
      TChgSL = TChgL if isFullRange else TChgL + BTHyst
      TChgSH = TChgH if isFullRange else TChgH - BTHyst

    elif CMD == CMD_GETDRI:
      await NetWriteEx(writer, CMD_ACKN)
      if OnBattery or Charging:
        await SendMessage(ErrorDRIFail, clWarn)
      else:  
        RI, VRI, ITest = GetDisRI(); BT = BTmpADC.Temperature()
        await SendMessage(MsgDRIDone+f'  RI: {RI:.1f} mΩ @ {BT:.2f} °C   [ VRI: {VRI:.1f} mV, ITest: {ITest:.1f} mA ]')

    elif CMD == CMD_GETCRI:
      await NetWriteEx(writer, CMD_ACKN)
      if OnBattery or Charging:
        await SendMessage(ErrorCRIFail, clWarn)
      else:  
        RI, VRI, ITest = GetChgRI(); BT = BTmpADC.Temperature()
        await SendMessage(MsgCRIDone+f'  RI: {RI:.1f} mΩ @ {BT:.2f} °C   [ VRI: {VRI:.1f} mV, ITest: {ITest:.1f} mA ]')

    elif CMD == CMD_UPDATERI:
      await NetWriteEx(writer, CMD_ACKN)
      if OnBattery or Charging:
        await SendMessage(ErrorRIBatBusy, clWarn)
      else:  
        RI, VRI, ITest = GetDisRI(); BT = BTmpADC.Temperature()
        BatRI = round(RI/BCRatio(BT))
        await SendMessage(MsgRIUpdated+f'  Measured: {RI:.1f} mΩ @ {BT:.2f} °C   Compensated: {BatRI} mΩ @ 25 °C')

    # ------- File Browser Requests -------      

    elif CMD == CMD_FLPQUERY: # has dedicated client
      path = await ReadWStr()   
      params = await NetReadEx(reader, 4)
      async with fsLock: 
        buff = PackPathQuery(path, bool(params[0]), bool(params[1]), bool(params[2]), bool(params[3]))
      await NetWriteEx(writer, struct.pack('<I', len(buff)))  
      await NetWriteBuffEx(writer, buff)

    elif CMD == CMD_FLGET: 
      move = bool(struct.unpack('<B', await NetReadEx(reader, 1))[0])
      wDrv, dirpath = PicoPath(await ReadWStr()); flist = []
      count = struct.unpack('<H', await NetReadEx(reader, 2))[0]
      if count > 1:
        for F in range(count): flist.append(await ReadWStr())
      elif count == 1:
        flist.append((await ReadWStr(), await ReadWStr()))
      await NetWriteEx(writer, CMD_ACKN) 
      await ForResult()  # create dest folders result 
      async with fsLock: await SendFiles(dirpath, flist, move)        

    elif CMD == CMD_FLSEND:
      dpath = await ReadWStr()
      KB = bool(struct.unpack('<B', await NetReadEx(reader, 1))[0])
      await NetWriteEx(writer, CMD_ACKN)
      wDrv, dpath = PicoPath(dpath)  
      async with fsLock: await RecvFiles(dpath, KB)

    elif CMD == CMD_FLDEL:
      wDrv, srcPath = PicoPath(await ReadWStr()); flist = []
      count = struct.unpack('<H', await NetReadEx(reader, 2))[0]
      for F in range(count):
        await NetReadEx(reader, 1)  # discard 
        flist.append(await ReadWStr())
      await NetWriteEx(writer, CMD_ACKN) 
      if (len(flist) == 1) and (JoinPath(srcPath, flist[0]) == ExceptFile):
        await EndWithError(ErrorExLogRO)      
      async with fsLock: await DeleteFiles(srcPath, flist)

    elif CMD == CMD_FLRENAME:
      wDrv, srcPath = PicoPath(await ReadWStr())
      oldFile = JoinPath(srcPath, await ReadWStr()) 
      newFile = JoinPath(srcPath, await ReadWStr())
      await NetWriteEx(writer, CMD_ACKN)
      try: 
        if (oldFile == ExceptFile) or (newFile == ExceptFile):
          await EndWithError(ErrorExLogRO)
        async with fsLock: os.rename(oldFile, newFile)
        await NetWriteEx(writer, SC_ACKN)
      except: await EndWithError(ErrorRename, oldFile)  

    elif CMD == CMD_FLMKDIR:
      wDrv, srcPath = PicoPath(await ReadWStr())
      dirPath = JoinPath(srcPath, await ReadWStr()) 
      await NetWriteEx(writer, CMD_ACKN)
      try: 
        async with fsLock: os.mkdir(dirPath)
        await NetWriteEx(writer, SC_ACKN)
      except: await EndWithError(ErrorMakeDir, dirPath)  

    # -------------------------------------  

    elif CMD == CMD_TERMPROG: 
      await NetWriteEx(writer, CMD_ACKN)
      TerminateProgram()
     
    else: await NetWriteEx(writer, CMD_NACK)
          
  except (asyncio.TimeoutError, IncompleteData, AbortWork): pass 
  except OSError as E:
    if E.errno != 104: LogException(ErrorHttp, E)    
  except Exception as E: LogException(ErrorCliHand, E) 
  finally:
    writer.close(); await writer.wait_closed(); gc.collect()
    if Debug: print(MsgCliDisconn)

# ------- HTTP Server --------------------------

async def HandleHTTP(reader, writer):
  try:
    import json
    request_line = await NetReadLineEx(reader)
    while await NetReadLineEx(reader) != b'\r\n': pass  

    if b'GET /data' in request_line:
      data = {'temp': round(Wtemp, 2), 'dew': round(Wdew, 2), 'hum': round(Whum, 2), 'pres': round(Wpres/100, 1)}
      body = json.dumps(data)
      headers = f'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n'
      await NetWriteEx(writer, headers)
      await NetWriteEx(writer, body)

    elif (b'GET / ' in request_line) or (b'GET /HTTP' in request_line):
      headers = f'HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: {len(html_page)}\r\n\r\n'
      await NetWriteEx(writer, headers)
      await NetWriteBuffEx(writer, html_page)

    else:
      msg = '404 Not Found'
      headers = f'HTTP/1.1 404 Not Found\r\nContent-Length: {len(msg)}\r\n\r\n'
      await NetWriteEx(writer, headers)
      await NetWriteEx(writer, msg)

  except (asyncio.TimeoutError, IncompleteData): pass 
  except OSError as E:
    if E.errno != 104: LogException(ErrorHttp, E)    
  except Exception as E: LogException(ErrorHttp, E) 
  finally:
    writer.close(); await writer.wait_closed()

# -----------------------------------------------

async def StartServers(TheIp, ThePort): 
  global CServer, HServer
  if CServer == None:  
    CServer = await asyncio.start_server(HandleClient, TheIp, ThePort)
  if HServer == None:  
    HServer = await asyncio.start_server(HandleHTTP, TheIp, 80)

async def StopServers():
  global CServer, HServer
  if CServer != None:
    CServer.close(); await CServer.wait_closed(); CServer = None
  if HServer != None:
    HServer.close(); await HServer.wait_closed(); HServer = None

async def NetworkTask():
  global SendRTI, RTIF, PicoIP, PicoPort, ReqPort
  TaskEnter('Network')
  ConLast = None if wlan.isconnected() else False 
  FirstCon = True; LogCon = False; wasSB = False; TConn = 0
  try:
    while not Terminated:
      ConNow = wlan.isconnected()

      if ConNow:
        if ConNow != ConLast:  
          # ------ Wifi just connected -------
          if LogCon: LogMsg(DebugFile, f'WiFi connected. Signal: {wlan.status('rssi')} dBm')
          UpdateNetLed(True)
          PicoIP = wlan.ifconfig()[0]
          if Debug: print(MsgWifiConned+PicoIP)
          if not ClockSynced:
            wasSB = await SyncRTC()
            if ClockSynced: await OnClockSynced() 
          await StartServers(PicoIP, PicoPort)
          if FirstCon: 
            await SendMessage(MsgBackOnline+f' ({ScriptVer[10:-1]}) !') 
            if not ClockSynced:
              if wasSB: await SendMessage(MsgClockBack, clWarn) 
              else: await SendMessage(MsgClkNotSync, clWarn) 
            FirstCon = False
          SendRTI = await CompAppVis()
          if SendRTI:  
            RTIF = 0; waitPower.set(); waitSens.set()            
          ConLast = ConNow   
        else:
          # ------ Wifi already connected ------
          if ReqPort != None:
            if ReqPort != PicoPort:
              await StopServers()
              PicoPort = ReqPort
              await StartServers(PicoIP, PicoPort)
            ReqPort = None

      else:
        if ConNow != ConLast:  
          # ----- Wifi just disconnected -----
          LogMsg(DebugFile, f'WiFi disconnected. Signal: {wlan.status('rssi')} dBm')
          UpdateNetLed(False)
          await StopServers()
          ConLast = ConNow; LogCon = True
          TConn = 0  
          # ----------------------------------
        if TConn > 0: TConn -= 1
        else:
          stat = wlan.status()
          if Debug: print(f'Wifi Status: {DecodeStat(stat)}')
          if stat != network.STAT_CONNECTING:
            if Debug: print(MsgWifiConning)
            wlan.connect(NET_SSID, NET_PASS)
          TConn = 5

      try: await asyncio.wait_for(waitNetw.wait(), 3)
      except asyncio.TimeoutError: pass
      waitNetw.clear()
  except asyncio.CancelledError: pass
  finally: TaskExit('Network')  

def DecodeStat(stat):
  if stat == network.STAT_IDLE:             return NetStatIdle
  elif stat == network.STAT_CONNECTING:     return NetStatConning
  elif stat == network.STAT_WRONG_PASSWORD: return NetStatWPass
  elif stat == network.STAT_NO_AP_FOUND:    return NetStatNoAP
  elif stat == network.STAT_CONNECT_FAIL:   return NetStatFail
  elif stat == network.STAT_GOT_IP:         return NetStatOK
  else:                                     return NetStatUnkn


# ------ Async Command Task ------------------

async def AsyncCMDTask():
  global Terminated, Charging
  TaskEnter('AsyncCMD')
  try:
    while not Terminated:
      await AsyncCMD.wait()
      while not Terminated:
        TaskCMD = GetAsyncCmd()  
        if TaskCMD == None: break

        if TaskCMD == tcChgStat:
          Charging = not bool(ChgStat.value())
          UpdateStatLed()

        elif TaskCMD == tcShutdown:
          await asyncio.sleep(1)
          if ShdReq.value() == 1: TerminateProgram()  
  
        await asyncio.sleep(0)
  except asyncio.CancelledError: pass
  finally: TaskExit('AsyncCMD')

def AsyncAddCmd(cmd):
  global idxAdd  
  if CmdBuff[idxAdd] != 0: return False    
  CmdBuff[idxAdd] = cmd
  idxAdd += 1
  if idxAdd == IRQCmds: idxAdd = 0
  AsyncCMD.set()
  return True
    
def GetAsyncCmd():
  global idxExec
  TheCmd = CmdBuff[idxExec]
  if TheCmd == 0: return None
  CmdBuff[idxExec] = 0  
  idxExec += 1
  if idxExec == IRQCmds: idxExec = 0      
  return TheCmd  


# ------ Misc Task (not wait for ) ----------

async def HourCheckTask():
  global BatRI, BatRITS
  while True:
    await asyncio.sleep(3600)
    UpdateUptime() 
    NowTS = time.time(); Diff = (NowTS - BatRITS) // 86400
    if ((BatRITS == 0) or (Diff > RIUpdTime)) and not (OnBattery or Charging):
      BatRI = round(GetDisRI()[0] / BCRatio(BTmpADC.Temperature())); BatRITS = NowTS
      await SendMessage(MsgBatRIUpd+f' {BatRI} mΩ')     

async def ClearBackupTask():
  await asyncio.sleep(1800)
  async with fsLock: RemoveBackup()
  CT = asyncio.current_task()
  if CT in OtherTasks: OtherTasks.remove(CT)   


# ------ Main Async Coro ---------------------  

async def main():
  global TaskList
  loop = asyncio.get_event_loop()
  loop.set_exception_handler(HandleAsyncExceptions)
  TaskList = []; AllTasksDone.clear()
  TaskList.append(asyncio.create_task(NetworkTask()))  
  TaskList.append(asyncio.create_task(PowerTask()))
  TaskList.append(asyncio.create_task(SensorsTask()))
  TaskList.append(asyncio.create_task(AsyncCMDTask()))
  OtherTasks.append(asyncio.create_task(HourCheckTask()))
  OtherTasks.append(asyncio.create_task(ClearBackupTask()))
  await AllTasksDone.wait()
  if Debug: print(MsgExitGrace)

async def AsyncSleep(sec):
  try: await asyncio.wait_for(waitOthers.wait(), sec)
  except asyncio.TimeoutError: pass

def HandleAsyncExceptions(loop, context):
  LogException(ErrorAsyncio, context['exception'], True)
  TerminateProgram()

def LogException(Head, Ex, setFault=False): 
  global Fault
  try:
    LineBreak = 40 * '-' 
    if setFault: Fault = True
    if Debug:
      print(LineBreak)
      print(Head)
      sys.print_exception(Ex)
      print(LineBreak)
    else: 
      with open(ExceptFile, 'a') as fExLog:
        DT = time.localtime(time.time())
        TimeStamp = '[ {:02d}-{:02d}-{:04d}, {:02d}:{:02d}:{:02d} ]'.format(DT[2], DT[1], DT[0], DT[3], DT[4], DT[5])  
        fExLog.write(LineBreak+'\n')
        fExLog.write(TimeStamp+'\n')
        fExLog.write(LineBreak+'\n')
        fExLog.write(Head+'\n')
        sys.print_exception(Ex, fExLog)  
  except: pass

def TaskEnter(name=''):
  if Debug and (name != ''): print(f'Task: {name} started')    
    
def TaskExit(name=''):
  CT = asyncio.current_task()
  if CT in TaskList: TaskList.remove(CT)    
  if len(TaskList) == 0: AllTasksDone.set()
  if Debug and (name != ''): print(f'Task: {name} ended')    

def TerminateProgram():
  global Terminated
  Terminated = True
  waitPower.set()
  waitSens.set()
  waitNetw.set()
  waitOthers.set()
  AsyncCMD.set()


#====== Entry Point ===================================  

try:
  Terminated      = False        
  Fault           = False
  UserAbort       = False
  TaskList        = []                         # the list of started Tasks
  OtherTasks      = []                         # instances of tasks that are not waited for
  AllTasksDone    = asyncio.ThreadSafeFlag()   # signal when all task are terminated
  waitPower       = asyncio.Event()            # wait on this in PowerTask 
  waitSens        = asyncio.Event()            # wait on this in SensorsTask
  waitNetw        = asyncio.Event()            # wait on this in NetworkTask
  waitOthers      = asyncio.Event()            # wait on this in all other tasks 
  fsLock          = asyncio.Lock()             # access lock for all async file system operations  
  pdLock          = asyncio.Lock()             # access lock for LD buffers

  idxAdd          = 0                          # the index where to add the new command
  idxExec         = 0                          # the index of the last unexecuted command
  IRQCmds         = 20                         # the number of the commands that can be bufferd
  CmdBuff         = bytearray(IRQCmds)         # async command buffer
  AsyncCMD        = asyncio.ThreadSafeFlag()   # wait on this for commands

  Wtemp           = 0                          # BME default temperature
  Wdew            = 0                          # BME default dew point
  Whum            = 0                          # BME default humidity 
  Wpres           = 1000                       # BME default pressure 

  UTLastTicks     = 0
  Uptime          = [0, 0, 0, 0, 0]            # (days, hours, mins, secs, ms)  

  tkSensInit      = 0                          # milliseconds since last try to initialize weather sensors

  wlan            = None
  Config          = None
  CServer         = None                       # the TCP server object
  HServer         = None                       # the HTTP server object
  
  OnBattery       = False                      # true when on battery, false when on main power
  Charging        = False                      # true when the Charger is ON
  SendRTI         = False                      # send real time info when True
  RTIF            = 0                          # number of consecutive RTI send failures
  BatRI           = 0                          # battery internal resistance at 25*C
  ChgStartReq     = False
  ChgStopReq      = False
  tkSelfDis       = 0                          # milliseconds since the last compensation of Battery Self-Discharge

  LIconst = 1 / (LIgain * RLshunt)
  BIconst = 1 / (BCgain * RBshunt)

  # --- GPIO Init ------------------------
  PowerEn  = Pin(pinPwrEn,  Pin.OUT, value=1)       # power auto-sustain: on
  LoadEn   = Pin(pinLoadEn, Pin.OUT, value=0)       # RI test load: off
  ChgEn    = Pin(pinChgEn,  Pin.OUT, value=0)       # battery charger: disabled
  ChgStat  = Pin(pinChgStat, Pin.IN, Pin.PULL_UP)   # charger status
  TmpAlt   = Pin(pinTmpAlt, Pin.IN, Pin.PULL_UP)    # temperatue alert / not used
  ShdReq   = Pin(pinShdReq,  Pin.IN, None)          # shutdown request
  UpdateStatLed()
  ShdReq.irq(trigger=Pin.IRQ_RISING, handler=ShutdownISR)
  ChgStat.irq(trigger=Pin.IRQ_FALLING | Pin.IRQ_RISING, handler=ChgStatISR)

  # --- Create Weather database ----------
  WData = Files.TimeDataStorage(WDataFile, 300, ((2, '<h', NoneTV), (2, '<H', NoneHV), (2, '<H', NonePV)), False, ResMem=35000)

  # --- RTC Init -------------------------
  CSync = Pin(pinCSync, Pin.OUT)  # 1bit memory flag 
  ClockSynced = bool(CSync.value())
  PicoRTC = RTC()
  if ClockSynced and Debug: print(RTCAlSynced+TimeStr())

  # --- Network Init ---------------------
  wlan = network.WLAN(network.STA_IF)
  wlan.active(True)
  PicoIP = 'none'; ReqPort = None
  UpdateNetLed()

  # --- I2C Sensors Init -----------------
  SensI2C  = I2C(0, scl=Pin(pinSensScl, pull=Pin.PULL_UP), sda=Pin(pinSensSda, pull=Pin.PULL_UP), freq=100000)
  PowerI2C = I2C(1, scl=Pin(pinPwrScl, pull=Pin.PULL_UP), sda=Pin(pinPwrSda, pull=Pin.PULL_UP), freq=100000)
  BmeReady = False; BMESens = None; AhtReady = False; AHTSens = None; InitSensors()
  BTmpADC  = Devices.TMP275(SensI2C, TempAddr)
  BatADC   = Devices.ADS1015(PowerI2C, BatAddr, Devices.DIF23, Devices.FSR512, Devices.SPS920)
  LoadADC  = Devices.ADS1015(PowerI2C, LoadAddr, Devices.DIF23, Devices.FSR512, Devices.SPS920)
  
  # --- Load settings --------------------
  Config    = Files.ConfigFile(IniFile, DefaultSettings)  
  LastRTC   = Config.GetIntKey('General', 'LastRTC')      # latest time stamp of the RTC
  PicoPort  = Config.GetIntKey('Network', 'PicoPort')     # own server port address
  CompIP    = Config.GetStrKey('Network', 'CompIP')       # IP address of computer
  CompPort  = Config.GetIntKey('Network', 'CompPort')     # port address of computer 
  BatRI     = Config.GetIntKey('Battery', 'BatRI')        # battery internal resistance (mR)
  BatRITS   = Config.GetIntKey('Battery', 'BatRITS')      # latest time stamp of internal resistance measured
  ChargerEn = Config.GetBoolKey('Battery', 'ChargerEn')   # battery charger enabled
  ChgIEnd   = Config.GetIntKey('Battery', 'ChgIEnd')      # battery charging termination current (mA)
  ChgVStop  = Config.GetIntKey('Battery', 'ChgStop')      # battery full charged voltage (mV)
  ChgVStart = Config.GetIntKey('Battery', 'ChgStart')     # battery recharge voltage (mV)
  BatVOff   = Config.GetIntKey('Battery', 'BatVOff')      # battery shutdown voltage (mV)
  FullCap   = Config.GetFloatKey('Battery', 'FullCap')    # relative total battery capacity (mAh)
  HoldCap   = Config.GetFloatKey('Battery', 'HoldCap')    # relative state of charge (mAh)
  SelfDisTS = Config.GetIntKey('Battery', 'SelfDisTS')    # latest time stamp of self discharge compensation
  TChgL     = Config.GetFloatKey('Battery', 'TChgL')      # minimum temperature when charging (°C)
  TChgH     = Config.GetFloatKey('Battery', 'TChgH')      # maximum temperature when charging (°C)
  TDisL     = Config.GetFloatKey('Battery', 'TDisL')      # minimum temperature when discharging (°C)
  TDisH     = Config.GetFloatKey('Battery', 'TDisH')      # maximum temperature when discharging (°C)
  
  # --- Final initializations ------------
  TChgSL = TChgL; TChgSH = TChgH; BChgSV = ChgVStart
  if ClockSynced: asyncio.run(OnClockSynced())
  gc.collect()

  # --- Main Async Loop ------------------
  asyncio.run(main())

except KeyboardInterrupt: UserAbort = True
except Exception as E: LogException(ErrorInEntry, E, True)
finally: Terminated = True

#====== Exit Point =====================================

try:      
  if Debug: print('Cleaning up...')

  ChgEn.value(0)    # Disable charging
  LoadEn.value(0)   # Disable RI test load
  ShdReq.irq(handler=None)
  ChgStat.irq(handler=None)

  if not Debug: 
    WData.FlushAll()
    SavePowerData()

  if ClockSynced:
    LastRTC = time.time()
    if (FullCap > 0) and (SelfDisTS > 0): BatSDComp()  
  if Config != None:  # Saving settings...
    Config.SetKey('General', 'LastRTC', LastRTC, check=True)
    Config.SetKey('Network', 'PicoPort', PicoPort, check=True)
    Config.SetKey('Network', 'CompIP', CompIP, check=True)
    Config.SetKey('Network', 'CompPort', CompPort, check=True)
    Config.SetKey('Battery', 'BatRI', BatRI, check=True)
    Config.SetKey('Battery', 'BatRITS', BatRITS, check=True)
    Config.SetKey('Battery', 'ChargerEn', ChargerEn, check=True)
    Config.SetKey('Battery', 'ChgIEnd', ChgIEnd, check=True)
    Config.SetKey('Battery', 'ChgStop', ChgVStop, check=True)
    Config.SetKey('Battery', 'ChgStart', ChgVStart, check=True)
    Config.SetKey('Battery', 'BatVOff', BatVOff, check=True)
    Config.SetKey('Battery', 'FullCap', float(round(FullCap, 3)), check=True)
    Config.SetKey('Battery', 'HoldCap', float(round(HoldCap, 3)), check=True)
    Config.SetKey('Battery', 'SelfDisTS', SelfDisTS, check=True)
    Config.SetKey('Battery', 'TChgL', TChgL, check=True)
    Config.SetKey('Battery', 'TChgH', TChgH, check=True)
    Config.SetKey('Battery', 'TDisL', TDisL, check=True)
    Config.SetKey('Battery', 'TDisH', TDisH, check=True)
    Config.Close()
    if Debug: print('Config handled')

  asyncio.run(StopServers())

  CL = clCrit if Fault else clNorm
  sdmsg = MsgRestBack if Fault and BackupExists() else MsgSysShd
  asyncio.run(SendMessage(sdmsg, CL))

  if not Debug and (wlan != None):
    wlan.disconnect()   # Disconnect from WiFi
    wlan.active(False)  # Deactivate the interface
    UpdateNetLed(False) # Turn Wifi LED off  

  if Debug: print('All done !')

except KeyboardInterrupt: UserAbort = True  
except Exception as E: LogException(ErrorInExit, E, True)
finally:
  UpdateStatLed()
  if not Debug:
    if Fault:
      if RestoreBackup(): time.sleep(5); reset()
    PowerEn.value(0) 
    if not Fault and not UserAbort: 
      time.sleep(5); reset()

