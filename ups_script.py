
#---------------- Main UPS Script v1.0 -----------------#
#                                                       #
#   Created by: Marus Alexander (Romania/Europe)        #
#   Contact and bug report: marus.gradinaru@gmail.com   #
#   Website link: https://marus-gradinaru.42web.io      #
#   Donation link: https://revolut.me/marusgradinaru    #
#                                                       #
#-------------------------------------------------------#


import asyncio, sys, time, select, struct, os, rp2, gc, io
from machine import ADC, Pin, PWM, I2C, Timer, RTC, mem32
from collections import OrderedDict

#----- GPIO Pin Definitions -------------

pinFanRPM   = 0
pinFanPWM   = 1
pinNasOn    = 2
pinNasAlert = 3
pinNasSda   = 4
pinNasScl   = 5
pinBAuto    = 6
pinBStart   = 7
pinBStop    = 8
pinBuzz     = 9
pinGrnLed   = 14
pinRedLed   = 15
pinOutSw    = 16
pinBatSw    = 17
pinAuxSda   = 18
pinAuxScl   = 19
pinAuxAlert = 20
pinPwrOff   = 21
pinRTCSync  = 22
pinUSB      = 24
pinBrdLed   = 25
pinVBat     = 26  # ADC0  
pinVPS      = 27  # ADC1
pinIChg     = 28  # ADC2
pinVsys     = 29  # ADC3

#----- ADC & Power Settings --------------

ADC_Vref = 3                      # volts
ADC_Step = (ADC_Vref / 4096)      # volts
ADC_Offset = 19                   # steps

VBat_Step = ADC_Step * 6.85       # volts
VBat_OverHyst = 10                # milivolts   / overvoltage +/- hysteresis
BCrtTime = 10                     # seconds     / battery critical time
BLowTime = 20                     # seconds     / battery low time
CritAckWait = 2                   # seconds     / wait for NAS to acknowledge the Bat Critical alert
CritShdWait = 30                  # seconds     / wait for NAS to shutdown

VPS_Step = ADC_Step * 6.84        # volts
VPS_OffLevel = 13000              # milivolts   / under this voltage PS is considered OFF [max]

OPA_Offset = 0.029 / ADC_Step     # volts (steps)
IChg_Ratio = 1.1
IChg_Other = 20                   # miliamps    / other loads connected to the charger
IChg_FloatHyst = 2                # miliamps    / charging current +/- hysteresis

VSys_Step = ADC_Step * 3          # volts

#------ Main Registry --------------------

REG_Vbat = 0     # milivolts   / Battery voltage
REG_Vps  = 0     # milivolts   / Power Supply voltage
REG_Vsys = 0     # milivolts   / Pico VSYS voltage
REG_Ichg = 0     # miliamps    / Battery charging current
REG_RPM  = 0     # rot/min     / Fan RPM
REG_Duty = 0     # percent     / Fan duty cycle
REG_TMP  = 0     # 1/100 *C    / Board Temperature

#------ NAS I2C Alert regs ---------------

regCMD        = 0xBD   # write: 4-byte commands / read: nothing
regRTC        = 0x1C   # write: 9-byte packed datetime / read: nothing
regAlert      = 0x7A   # write: nothing / read: 12 bytes (3 x 4-byte registers)
regMain       = 0xE4   # write: nothing / read: 13 bytes
regFanCfg     = 0x58   # write: 11 bytes / read nothing
regSilentCfg  = 0x9B   # write: 11 bytes / read nothing
regBatCfg     = 0xD2   # write: 14 bytes / read nothing
regBatLow     = 0xD3   # write: 2 bytes / read nothing
regShdState   = 0xA6   # write: 1 bytes / read nothing

sigContinue   = 0xCC
sigRetry      = 0x33
sigStop       = 0x69

cmdPowerOff   = b'\xB1\x83\x6A\x4D'
cmdRstReady   = b'\x83\xB1\xC7\xA6'
cmdShdReady   = b'\xB1\x83\x6A\xC7'
cmdReadBat    = b'\xA6\x3D\x81\xF7'
cmdReadTerm   = b'\x52\xE9\x4B\x83'

stNone        = b'\x01\x01\x01\x01'
stShdNow      = b'\x57\xDF\x48\x9B'
stShdLow      = b'\x84\x75\xB9\xFD'
stPowerON     = b'\x72\xC4\x9A\x31'
stPowerOFF    = b'\xA9\x27\x13\x4C'
stBatON       = b'\x6E\x24\xA5\xD3'
stBatOFF      = b'\x5A\xE6\x3D\x42'
stBatOver     = b'\x41\xF8\xA5\x27'

REG_Shutdown  = stNone
REG_Power     = stNone
REG_Battery   = stNone
REG_BatOver   = stNone

#------ Main Tasks timing --------------

I2CTask_time     = 0.10
InputTask_time   = 0.27
BoardTask_time   = 0.63
PowerTask_time   = 0.95
TempTask_time    = 1.12
TimeOvrTask_time = 1.82

#------ Task commands ------------------

tcBeep     = 1   # make a beep
tcError    = 2   # make an error beep
tcStTimer  = 3   # start the Start Timer
tcSp1Timer = 4   # start the Stop Timer 1
tcSp2Timer = 5   # start the Stop Timer 2
tcInput    = 6   # start Task Input
tcUsbTimer = 7   # start USB debouncing timer

#------ Used files ---------------------

IniFile  = '/ups_cfg.ini'
BatFile  = '/batvi.bin'
TermFile = '/term.bin'

#------ Default Settings ---------------

DefaultSettings = """
[Fan]
Auto = yes
LowTemp = 3150
HighTemp = 3350
LowDuty = 20
HighDuty = 100
FixDuty = 35

[Silent]
Enabled = yes
StartHour = 22
StartMin = 30
StopHour = 8
StopMin = 0
MaxFDuty = 40

[Batterry]
Overvoltage = 13900
Autostart = 12500
LowBat = 11800
Critical = 11500
Disconnected = 5000
ChgBulk = 900
ChgFloat = 10
"""

#------ CRC8 table ---------------------

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


#------ Status Led Class ------------------

class StatLed:
  Off    = 0
  Green  = 1
  Red    = 2
  Orange = 3

  def __init__(self, pGreen, pRed):
    self.GrnLed = Pin(pGreen, Pin.OUT, value=0) 
    self.RedLed = Pin(pRed, Pin.OUT, value=0)
    self.FState = self.Off
    
  def state(self, color=None):  
    if not isinstance(color, int): return self.FState
    if color != self.FState:
      if color == self.Green:
        self.GrnLed.on()
        self.RedLed.off()
      elif color == self.Red:
        self.GrnLed.off()
        self.RedLed.on()
      elif color == self.Orange:
        self.GrnLed.on()
        self.RedLed.on()
      else:
        self.GrnLed.off()
        self.RedLed.off()
      self.FState = color
    
  def toggle(self, led=None):
    if (led == self.Green) or (led == None):  
      self.GrnLed.value(not self.GrnLed.value())     
      self.FState = self.FState ^ 0b01
    if (led == self.Red) or (led == None):  
      self.RedLed.value(not self.RedLed.value())
      self.FState = self.FState ^ 0b10
    self.FState = self.FState & 0b11  
        

#------ Average Class -------------------

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
    self.Items = [0] * NewSize
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


#------ Config File Class ---------------------

class ConfigFile:
  def __init__(self, cfg_file, def_str='', save_to=300):  
    self.TheFile = cfg_file
    self.timer = Timer()
    self.timeout = save_to
    self.CFG = OrderedDict()
    if def_str != '': self.ReadStr(def_str)
    try: self.ReadFile(cfg_file)
    except OSError: pass
    self.modified = False

  def _timer_callback(self, timer):
    if self.modified: self.SaveFile()  
    
  def _read_obj(self, Obj):
    curr_sect = None; modif = False  
    for line in Obj:
      line = line.strip()
      if line.startswith('[') and line.endswith(']'):
        curr_sect = line[1:-1]
        if curr_sect not in self.CFG:
          self.CFG[curr_sect] = OrderedDict()
          modif = True
      elif ('=' in line) and (curr_sect != None):
        key, value = line.split('=', 1)
        self.CFG[curr_sect][key.strip()] = value.strip()
        modif = True
    if modif: self.Modified()

  def Close(self):
    self.timer.deinit()  
    if self.modified: self.SaveFile()  

  def Modified(self):
    self.modified = True
    self.timer.init(period=(self.timeout*1000), mode=Timer.ONE_SHOT, callback=self._timer_callback)

  def Clear(self):
    self.CFG.clear()
    self.Modified()

  def ReadStr(self, def_str):
    with io.StringIO(def_str) as iniFile: self._read_obj(iniFile)

  def ReadFile(self, filename):
    with open(filename, 'r') as iniFile: self._read_obj(iniFile)

  def SaveFile(self):
    with open(self.TheFile, 'w') as iniFile:
      for sect, opts in self.CFG.items():
        iniFile.write(f'[{sect}]\n')
        for key, value in opts.items():
          iniFile.write(f'{key} = {value}\n')
        iniFile.write('\n')
      self.modified = False

  def List(self):
    for sect, opts in self.CFG.items():
      print(f'[{sect}]')
      for key, value in opts.items():
        print(f'{key} = {value}')
      print('')
      
  def DelKey(self, section, key=None):
    if section in self.CFG:
      if key == None:
        del self.CFG[section]
        self.Modified()
      elif key in self.CFG[section]:
        del self.CFG[section][key]
        self.Modified()
            
  def SetKey(self, section, key, value):
    if section not in self.CFG:
      self.CFG[section] = OrderedDict()
    if isinstance(value, bool):
      self.CFG[section][key] = 'yes' if value else 'no'  
    else: self.CFG[section][key] = str(value)
    self.Modified()
    
  def GetStrKey(self, section, key, default=None):
    try: return self.CFG[section][key]
    except: return default

  def GetIntKey(self, section, key, default=None):
    try: return int(self.CFG[section][key])
    except: return default 

  def GetBoolKey(self, section, key, default=None):
    try:  
      v = self.CFG[section][key].lower()
      return True if (v == 'yes') or (v == 'true') or (v == '1') else False
    except: return default


#------ TMP275 Sensor Class -------------------

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
    self.I2C.writeto(self.Addr, bytes([self.conf_reg, CONF]))

  def SetPointer(self, Reg):
    self.I2C.writeto(self.Addr, bytes([Reg]))

  def Temperature(self):
    raw = self.I2C.readfrom(self.Addr, 2)
    LSB = ((raw[1] >> self.B2_shift) & self.B2_mask) * self.Resolution
    return int((raw[0]+LSB)*100)

  def GetTempAlert(self, Reg):
    self.I2C.writeto(self.Addr, bytes([Reg]))
    raw = self.I2C.readfrom(self.Addr, 2)
    LSB = ((raw[1] >> 4) & 0x0F) * self.Resolution
    return round(raw[0]+LSB, 2)

  def SetTempAlert(self, Reg, Value):
    if Value > 127.9375: Value = 127.9375
    Value = int(Value / 0.0625)
    B1 = (Value >> 4) & 0xFF
    B2 = (Value << 4) & 0xF0
    self.I2C.writeto(self.Addr, bytes([Reg, B1, B2]))


#------ I2C Slave Class --------------------------

class I2CSlave:

  # Register base addresses, offsets and bit mask definitions for GPIO

  IO_BANK0_BASE    = 0x40014000
  GPIO_REG_BLOCK_SIZE = 8
  GPIO_CTRL           = 0x004    # [32bit] GPIO control including function select and overrides
  _FUNCSEL               = 0x1F  #   [bit.4:0] Function select mask
  _FUNCSEL_I2C           = 0x03  #   [bit.4:0] I2C select value

  PADS_BANK0_BASE  = 0x4001C000
  _PDE                   = 0x04
  _PUE                   = 0x08
   
  # Register base addresses, offsets and bit mask definitions for I2C

  I2C0_BASE        = 0x40044000
  I2C1_BASE        = 0x40048000

  IC_CON              = 0x00     # [32bit] I2C Control Register
  _MASTER_MODE           = 0x01  #   [bit.0] 0: Master mode is disabled / 1: Master mode is enabled
  _IC_10BITADDR_SLAVE    = 0x08  #   [bit.3] 0: 7-bit addressing        / 1: 10-bit addressing
  _IC_SLAVE_DISABLE      = 0x40  #   [bit.6] 0: Slave mode is enabled   / 1: Slave mode is disabled

  IC_TAR              = 0x04     # [32bit] I2C Target Address Register

  IC_SAR              = 0x08     # [32bit] I2C Slave Address Register
  _IC_SAR_7BIT           = 0x3F  #   [bit.6:0] 7bit Slave address

  IC_DATA_CMD         = 0x10     # [32bit] I2C Rx/Tx Data Buffer and Command Register
  
  IC_RAW_INTR_STAT    = 0x34     # [32bit] I2C Raw Interrupt Status Register
  _RD_REQ                = 0x20  #   [bit.5] 0: no read request  / 1: read request from master       
  
  IC_RX_TL            = 0x38     # [32bit] I2C Receive FIFO Threshold Register
  IC_TX_TL            = 0x3C     # [32bit] I2C Transmit FIFO Threshold Register
  IC_CLR_INTR         = 0x40     # [32bit] Clear Combined and Individual Interrupt Register
  IC_CLR_RD_REQ       = 0x50     # [32bit] Clear RD_REQ Interrupt Register
  
  IC_CLR_TX_ABRT      = 0x54     # [32bit] Clear TX_ABRT Interrupt Register
  _CLR_TX_ABRT           = 0x01  #   [bit.0] Read this register to clear the TX_ABRT interrupt
  
  IC_ENABLE           = 0x6C     # [32bit] I2C ENABLE Register
  _ENABLE                = 0x01  #   [bit.0] 0: Disabled    / 1: Enabled
  
  IC_STATUS           = 0x70     # [32bit] I2C STATUS Register
  _RFNE                  = 0x08  #   [bit.3] 0: Receive FIFO empty      / 1: Receive FIFO contains data
  _TFE                   = 0x04  #   [bit.2] 0: Transmit FIFO not empty / 1: Transmit FIFO is empty
  _TFNF                  = 0x02  #   [bit.1] 0: Transmit FIFO full      / 1: Transmit FIFO not full

  # Atomic Register Access

  reg_rw  = 0x0000  # normal read write access
  reg_xor = 0x1000  # atomic XOR on write
  reg_set = 0x2000  # atomic bitmask set on write
  reg_clr = 0x3000  # atomic bitmask clear on write

  # Set bits in Pico IO Control register      
  def set_reg_ioctrl(self, pin, data):
    offset = self.GPIO_CTRL + self.GPIO_REG_BLOCK_SIZE * pin  
    mem32[ self.IO_BANK0_BASE | self.reg_set | offset ] = data
        
  # Clear bits in Pico IO Control register      
  def clr_reg_ioctrl(self, pin, data):
    offset = self.GPIO_CTRL + self.GPIO_REG_BLOCK_SIZE * pin  
    mem32[ self.IO_BANK0_BASE | self.reg_clr | offset ] = data

  # Set bits in Pico Pad Control register      
  def set_reg_iopad(self, pin, data):
    mem32[ self.PADS_BANK0_BASE | self.reg_set | (pin+1) * 4 ] = data
        
  # Clear bits in Pico Pad Control register      
  def clr_reg_iopad(self, pin, data):
    mem32[ self.PADS_BANK0_BASE | self.reg_clr | (pin+1) * 4 ] = data

  # Write Pico I2C register
  def write_reg_i2c(self, reg_offset, data, method=0):
    mem32[ self.i2c_base | method | reg_offset ] = data
    
  # Read Pico I2C register  
  def read_reg_i2c(self, reg_offset):
    return mem32[ self.i2c_base | reg_offset ]
        
  # Set bits in Pico I2C register      
  def set_reg_i2c(self, reg_offset, data):
    self.write_reg_i2c(reg_offset, data, method=self.reg_set)
        
  # Clear bits in Pico I2C register      
  def clr_reg_i2c(self, reg_offset, data):
    self.write_reg_i2c(reg_offset, data, method=self.reg_clr)
       
  # Create class instance and initialize I2C as Slave
  #   i2cID - The internal Pico I2C device to use (0 or 1)
  #   sda/scl - The GPIO number of the pin to use for SDA and SCL
  #   slaveAddr - The I2C address to assign to this slave
  def __init__(self, i2cID=0, sda=0,  scl=1, slaveAddr=0x41):
    self.i2c_ID = i2cID
    self.i2c_base = self.I2C0_BASE if self.i2c_ID == 0 else self.I2C1_BASE 
    self.slaveAddr = slaveAddr
    self.SCL = scl; self.SDA = sda
    # Disable I2C engine while initializing it
    self.clr_reg_i2c(self.IC_ENABLE, self._ENABLE)
    # Configure Slave address bits
    self.clr_reg_i2c(self.IC_SAR, self._IC_SAR_7BIT)
    self.set_reg_i2c(self.IC_SAR, self._IC_SAR_7BIT & self.slaveAddr)
    # Configure as 7bit addres Slave
    self.clr_reg_i2c(self.IC_CON, self._MASTER_MODE | self._IC_10BITADDR_SLAVE | self._IC_SLAVE_DISABLE)
    # Configure SDA/SCL pins to I2C function
    self.clr_reg_iopad(sda, self._PDE)
    self.set_reg_iopad(sda, self._PUE)
    self.clr_reg_ioctrl(sda, self._FUNCSEL)
    self.set_reg_ioctrl(sda, self._FUNCSEL_I2C)
    self.clr_reg_iopad(scl, self._PDE)
    self.set_reg_iopad(scl, self._PUE)
    self.clr_reg_ioctrl(scl, self._FUNCSEL)
    self.set_reg_ioctrl(scl, self._FUNCSEL_I2C)
    # Enable I2C engine 
    self.set_reg_i2c(self.IC_ENABLE, self._ENABLE)
    
  def deinit(self):
    # Disable I2C engine while initializing it
    self.clr_reg_i2c(self.IC_ENABLE, self._ENABLE)
    # Configure as Master
    self.write_reg_i2c(self.IC_CON, 0x63)
    # Enable I2C engine 
    self.set_reg_i2c(self.IC_ENABLE, self._ENABLE)    

  def ReadRequest(self):
    status = mem32[ self.i2c_base | self.IC_RAW_INTR_STAT ] & self._RD_REQ
    return bool(status)

  def SendNone(self):
    while True:
      self.read_reg_i2c(self.IC_CLR_TX_ABRT)  
      self.read_reg_i2c(self.IC_CLR_RD_REQ)
      mem32[ self.i2c_base | self.IC_DATA_CMD ] = 0x00
      time.sleep_ms(2)
      if (mem32[ self.i2c_base | self.IC_RAW_INTR_STAT ] & self._RD_REQ) == 0: break

  def SendDataByte(self, data):
    buff = struct.pack('<B', data)
    self.SendDataBlock32(buff)

  def SendDataWord(self, data):
    buff = struct.pack('<H', data)
    self.SendDataBlock32(buff)

  def SendDataDWord(self, data):
    buff = struct.pack('<I', data)
    self.SendDataBlock32(buff)

  def SendDataBlock32(self, data, start=0, count=32, to_ms=5, crc=False):
    self.read_reg_i2c(self.IC_CLR_TX_ABRT)  
    self.read_reg_i2c(self.IC_CLR_RD_REQ)
    if crc and (count >= 32): count = 31
    stop = start + count
    if stop > len(data): stop = len(data)
    if stop <= start: return True
    if crc:
      CRC = 0; table = crc8_tab
      for i in range(start, stop): CRC = table[CRC ^ data[i]]
    half = start + 16
    for i in range(start, stop+int(crc)):
      if (i == start) or (i == half):
        if not self.WaitToSend(to_ms): return False
      if crc and (i == stop): mem32[ self.i2c_base | self.IC_DATA_CMD ] = CRC
      else: mem32[ self.i2c_base | self.IC_DATA_CMD ] = data[i]
    return True  

  def WaitToSend(self, ms=5):
    count = ms * 100
    while ((mem32[ self.i2c_base | self.IC_STATUS] & self._TFE) == 0) and (count > 0):
      time.sleep_us(10)
      count -= 1
    return (count > 0) 

  def DataAvailable(self, ms=5):
    count = ms * 10
    while ((mem32[ self.i2c_base | self.IC_STATUS] & self._RFNE) == 0) and (count > 0):
      time.sleep_us(100)
      count -= 1
    return (count > 0) 

  def ReadDataByte(self):
    if not self.DataAvailable(): return None
    return mem32[self.i2c_base | self.IC_DATA_CMD] & 0xFF

  def ReadDataBlock16(self, count=0, timeout_ms=5):
    data = b''
    if (count < 1) or (count > 16): count = 16
    while len(data) < count:
      if not self.DataAvailable(timeout_ms): break
      data = data + bytes([mem32[self.i2c_base | self.IC_DATA_CMD] & 0xFF])
    return data


#------ Pulse Counter Class --------------------------

@rp2.asm_pio()
def pulse_counter():
  label('loop')
  wait(0, pin, 0)
  wait(1, pin, 0)
  jmp(x_dec, 'loop') 

class PulseCounter:
  def __init__(self, sm_id, pin):  # pin is machine.Pin instance
    self.sm = rp2.StateMachine(0, pulse_counter, in_base=pin)
    self.sm.put(0)
    self.sm.exec('pull()')
    self.sm.exec('mov(x, osr)')
    self.sm.active(1)
    self.LastTicks = time.ticks_ms()

  def GetCount(self):
    self.sm.exec('mov(isr, x)')
    self.sm.exec('push()')
    return -self.sm.get() & 0x7FFFFFFF

  def GetCountReset(self):
    self.sm.put(0)
    self.sm.exec('pull()')
    self.sm.exec('mov(isr, x)')
    self.sm.exec('mov(x, osr)')
    self.sm.exec('push()')
    return -self.sm.get() & 0x7FFFFFFF

  def GetFreq(self):
    self.sm.put(0)
    self.sm.exec('pull()')
    self.sm.exec('mov(isr, x)')
    self.sm.exec('mov(x, osr)')
    NewTicks = time.ticks_ms()
    self.sm.exec('push()')
    Pulses = -self.sm.get() & 0x7FFFFFFF
    Time = time.ticks_diff(NewTicks, self.LastTicks)
    self.LastTicks = NewTicks
    return (Pulses / Time) * 1000
    
  def deinit(self):
    self.sm.active(0)


#------ ISR Code -----------------------------

def StartISR(pin):
  global BStart_LPT
  CurrTime = time.ticks_ms()
  Diff = time.ticks_diff(CurrTime, BStart_LPT)
  if Diff > 1000:
    BStart_LPT = CurrTime
    AsyncAddCmd(tcStTimer)

def StartTimerISR(timer):
  global StartWhenReady  
  if BStart.value() == 0:
    if REG_Vbat <= VBat_LowLevel:
      AsyncAddCmd(tcError)
    else:
      OutSwitch.on()
      AsyncAddCmd(tcBeep)
      REG_Shutdown = stNone
      StartWhenReady = False
    if DebugBTN: print('True START signal detected !')
  else:
    if DebugBTN: print('False START signal detected !')

def StopISR(pin):
  global BStop_LPT
  CurrTime = time.ticks_ms()
  Diff = time.ticks_diff(CurrTime, BStop_LPT)
  if Diff > 4000:
    BStop_LPT = CurrTime
    AsyncAddCmd(tcSp1Timer)

def StopTimer1ISR(timer):
  if BStop.value() == 0:
    AsyncAddCmd(tcSp2Timer)
    AsyncAddCmd(tcBeep)
  else:
    if DebugBTN: print('False STOP signal detected !')

def StopTimer2ISR(timer):
  global REG_Shutdown, StartWhenReady
  if BStop.value() == 0:
    OutSwitch.off()
    if DebugBTN: print('Forced Stop requested.')
  else:
    if NasOn.value() == 0:
      OutSwitch.off()
    else:
      REG_Shutdown = stShdNow  
      UpdateNasAlert(True) 
    if DebugBTN: print('Graceful Stop requested.')
  AsyncAddCmd(tcBeep)
  StartWhenReady = False

def CriticalISR(timer):
  global IsrBatCrit, BCTRunning
  IsrBatCrit = True
  BCTRunning = False

def LowBatISR(timer):
  global IsrBatLow, BLTRunning
  IsrBatLow = True
  BLTRunning = False
  
def USBPowerISR(pin):
  global Usb_LCT
  CurrTime = time.ticks_ms()
  Diff = time.ticks_diff(CurrTime, Usb_LCT)
  if Diff > 800:
    Usb_LCT = CurrTime
    AsyncAddCmd(tcUsbTimer)
    
def USBTimerISR(timer):    
  if USBPower.value() == 1: AsyncAddCmd(tcInput)


#------ Basic Functions --------------------------

def Duty(perc):
  return int(0xFFFF * perc / 100)

def FormatBytes(data):
  return ' '.join(['{:02x}'.format(byte) for byte in data]).upper()

def OnUSB():
  return USBPower.value() == 1

def CanPowerOff():
  return GetVps() <= VPS_OffLevel
#   return (not OnUSB()) and (GetVps() <= VPS_OffLevel)  # used on debuging

def SetAutoStart():
  with open('/autostart', 'w') as asFile:
    asFile.write('yes')

def ClearAutoStart():
  with open('/autostart', 'w') as asFile:
    asFile.write('no')

def AutoStart():
  try:  
    with open('/autostart', 'r') as asFile:
      AST = asFile.read().strip().lower()
    return True if AST == 'yes' else False
  except: return False

def FanDutyCycle(Temp):
  if not FanAuto: return FixDuty
  elif Temp <= LowTemp: return 0
  elif Temp >= HighTemp: return HighDuty
  else: return ((Temp - LowTemp) * DPG) + LowDuty

def FilterDC(Value, Step):
  X = round(Value / Step)
  return X * Step

def SplitInputCmd(line):
  i = line.find(':')
  if i < 0: return line.strip(), None
  CRes = line[:i].strip()
  PRes = line[i+1:].strip()
  try:
    if CRes == 'bat': PRes = float(PRes)  
    else: PRes = int(PRes)
  except:
    PRes = None      
  return CRes, PRes

def PrintTime():
  DT = PicoRTC.datetime()
  LTS = '{:02d}-{:02d}-{:04d}, {:02d}:{:02d}:{:02d}'.format(DT[2], DT[1], DT[0], DT[4], DT[5], DT[6])
  print('Pico time: ', LTS)
  
def PassedMins():
  DT = PicoRTC.datetime()
  return (DT[4] * 60) + DT[5]

def UpdateNasAlert(newState):
  oldState = NasAlert.value()
  NasAlert.off()
  if newState and (NasOn.value() == 1): 
    if oldState: time.sleep_ms(10)
    NasAlert.on()
    
def UpdateStatLed():
  if not StLUpdate: return  
  if (REG_Vps > VPS_OffLevel) and (REG_Vbat > VBat_LowLevel) and BatFull: StLed.state(StatLed.Green)
  elif (REG_Vbat <= VBat_LowLevel) or (REG_Ichg >= IChg_BulkLevel) or (REG_BatOver == stBatOver): StLed.state(StatLed.Red)
  else: StLed.state(StatLed.Orange)

def PowerOffExit():
  Buzzer.init(freq=200)
  try:
    Buzzer.duty_u16(Duty(1.5)) 
    time.sleep_ms(500)
  finally:
    Buzzer.duty_u16(BuzOFF)
  OutSwitch.off(); BatSwitch.off()  
  Pin(pinPwrOff, Pin.OUT, value=1)  
  time.sleep(5)
  sys.exit()  

def WellcomeBuzz():
  BuzON = Duty(2)
  try:
    Buzzer.init(freq=1000, duty_u16=BuzON)
    time.sleep_ms(40)
    Buzzer.duty_u16(BuzOFF)
    time.sleep_ms(80)
    Buzzer.init(freq=1500, duty_u16=BuzON)
    time.sleep_ms(70)
  finally:
    Buzzer.duty_u16(BuzOFF)

def GetSoundEn():
  if not SilentMode or not ClockSynced: return True
  CT = PicoRTC.datetime()
  currTime  = (CT[4] * 60) + CT[5]
  startTime = (SilentSTH * 60) + SilentSTM
  stopTime  = (SilentSPH * 60) + SilentSPM
  if startTime < stopTime:
    return (currTime < startTime) or (currTime > stopTime)
  else:
    return (currTime < startTime) and (currTime > stopTime)

def AddBatVI(mV, mA):
  Vdata = struct.pack('<H', mV)
  Idata = struct.pack('<H', mA)
  idxBat = struct.unpack('<H', BatVIBuff[Pstart:])[0]
  BatVIBuff[idxBat] = Vdata[0]
  BatVIBuff[Istart+idxBat] = Idata[0]
  idxBat += 1
  BatVIBuff[idxBat] = Vdata[1]
  BatVIBuff[Istart+idxBat] = Idata[1]
  idxBat += 1
  if idxBat >= Istart: idxBat = 0
  BatVIBuff[Pstart:] = struct.pack('<H', idxBat)
  
def SaveBatVI():
  DT = PicoRTC.datetime()
  TimeBuff = struct.pack('<HHHHH', DT[0], DT[1], DT[2], DT[4], DT[5])
  with open(BatFile, 'wb') as batFile:
    batFile.write(BatVIBuff)
    batFile.write(TimeBuff)

def AddTerm(tmp, dcy):
  Tdata = struct.pack('<H', tmp)
  Ddata = struct.pack('<H', dcy)
  idxTerm = struct.unpack('<H', TermBuff[Qstart:])[0]
  TermBuff[idxTerm] = Tdata[0]
  TermBuff[Dstart+idxTerm] = Ddata[0]
  idxTerm += 1
  TermBuff[idxTerm] = Tdata[1]
  TermBuff[Dstart+idxTerm] = Ddata[1]
  idxTerm += 1
  if idxTerm >= Dstart: idxTerm = 0
  TermBuff[Qstart:] = struct.pack('<H', idxTerm)

def SaveTerm():
  DT = PicoRTC.datetime()
  TimeBuff = struct.pack('<HHHHH', DT[0], DT[1], DT[2], DT[4], DT[5])
  with open(TermFile, 'wb') as termFile:
    termFile.write(TermBuff)
    termFile.write(TimeBuff)
    
def SaveGraphs():
  if ClockSynced:
    SaveBatVI()
    SaveTerm()
  else:
    try: os.remove(BatFile)
    except: pass
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
      NT = PicoRTC.datetime()
      GTS = time.mktime((GT[0], GT[1], GT[2], GT[3], GT[4], 0, 0, 0))
      NTS = time.mktime((NT[0], NT[1], NT[2], NT[4], NT[5], 0, 0, 0))
      MDiff = (NTS - GTS) // 60; Diff = MDiff * 2
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
  if GraphsHandled or not ClockSynced: return
  RestoreGr(BatVIBuff, BatFile)
  RestoreGr(TermBuff, TermFile)
  try: os.remove(BatFile)
  except: pass
  try: os.remove(TermFile)
  except: pass  
  GraphsHandled = True

def SendI2CBuff(buff):
  bPos = 0
  while True:
    Sig = NasI2C.ReadDataByte()
    if Sig == sigContinue:
      bPos += 31
      if bPos >= len(buff): bPos = 0
      NasI2C.SendDataBlock32(buff, bPos, crc=True)
    elif Sig == sigRetry:
      NasI2C.SendDataBlock32(buff, bPos, crc=True)
    elif Sig == sigStop: return True
    else: return False


#------ Settings -------------------------------
    
def PackFanCfg():
  try:  
    LFanAuto  = Config.GetBoolKey('Fan', 'Auto', False)
    LLowTemp  = Config.GetIntKey('Fan', 'LowTemp', 0)
    LHighTemp = Config.GetIntKey('Fan', 'HighTemp', 0)
    LLowDuty  = Config.GetIntKey('Fan', 'LowDuty', 0)
    LHighDuty = Config.GetIntKey('Fan', 'HighDuty', 0)
    LFixDuty  = Config.GetIntKey('Fan', 'FixDuty', 0)
    return struct.pack('<BHHHHH', int(LFanAuto), LLowTemp, LHighTemp, LLowDuty, LHighDuty, LFixDuty)    
  except: return b'\x00' * 11
    
def SetFanConfig(FanBuff):
  global FanAuto, LowTemp, HighTemp, LowDuty, HighDuty, FixDuty, DPG
  if FanBuff == PackFanCfg():
    if DebugI2C: print('Received the same Fan settings.')
    return True
  try:
    FanAuto, LowTemp, HighTemp, LowDuty, HighDuty, FixDuty = struct.unpack('<BHHHHH', FanBuff)
    FanAuto = bool(FanAuto)
    Config.SetKey('Fan', 'Auto', FanAuto)
    Config.SetKey('Fan', 'LowTemp', LowTemp)
    Config.SetKey('Fan', 'HighTemp', HighTemp)
    Config.SetKey('Fan', 'LowDuty', LowDuty)
    Config.SetKey('Fan', 'HighDuty', HighDuty)
    Config.SetKey('Fan', 'FixDuty', FixDuty)
    DPG = (HighDuty - LowDuty) / (HighTemp - LowTemp)
    if DebugI2C: print('Fan settings updated.')
    return True
  except: return False    


def PackSilentCfg():
  try:  
    LSilMode = Config.GetBoolKey('Silent', 'Enabled', False)
    LSilSTH  = Config.GetIntKey('Silent', 'StartHour', 0)
    LSilSTM  = Config.GetIntKey('Silent', 'StartMin', 0)
    LSilSPH  = Config.GetIntKey('Silent', 'StopHour', 0)
    LSilSPM  = Config.GetIntKey('Silent', 'StopMin', 0)
    LMaxDuty = Config.GetIntKey('Silent', 'MaxFDuty', 0)
    return struct.pack('<BHHHHH', int(LSilMode), LSilSTH, LSilSTM, LSilSPH, LSilSPM, LMaxDuty)
  except: return b'\x00' * 11
    
def SetSilentConfig(SilBuff):
  global SoundEn, SilentMode, SilentSTH, SilentSTM, SilentSPH, SilentSPM, MaxFDuty
  if SilBuff == PackSilentCfg():
    if DebugI2C: print('Received the same Silent settings.')
    return True
  try:
    SilentMode, SilentSTH, SilentSTM, SilentSPH, SilentSPM, MaxFDuty = struct.unpack('<BHHHHH', SilBuff)
    SilMode = bool(SilentMode)
    Config.SetKey('Silent', 'Enabled', SilMode)
    Config.SetKey('Silent', 'StartHour', SilentSTH)
    Config.SetKey('Silent', 'StartMin', SilentSTM)
    Config.SetKey('Silent', 'StopHour', SilentSPH)
    Config.SetKey('Silent', 'StopMin', SilentSPM)
    Config.SetKey('Silent', 'MaxFDuty', MaxFDuty)
    if DebugI2C: print('Silent settings updated.')
    SoundEn = GetSoundEn()
    if not SoundEn and REG_Duty > MaxFDuty:
      REG_Duty = MaxFDuty
      FanPWM.duty_u16(Duty(REG_Duty))    
    return True
  except: return False    


def PackBatteryCfg():
  try:  
    LBatOver  = Config.GetIntKey('Battery', 'Overvoltage', 0)
    LBatStart = Config.GetIntKey('Battery', 'Autostart', 0)
    LBatCrit  = Config.GetIntKey('Battery', 'Critical', 0)
    LBatOff   = Config.GetIntKey('Battery', 'Disconnected', 0)
    LBatBulk  = Config.GetIntKey('Battery', 'ChgBulk', 0)
    LBatFloat = Config.GetIntKey('Battery', 'ChgFloat', 0)
    return struct.pack('<HHHHHH', LBatOver, LBatStart, LBatCrit, LBatOff, LBatBulk, LBatFloat)
  except: return b'\x00' * 12
  
def SetBatteryConfig(BatBuff):
  global VBat_OverLevel, VBat_ReadyLevel, VBat_LowLevel, VBat_CritLevel, VBat_OffLevel, IChg_BulkLevel, IChg_FloatLevel
  try:
    VBat_LowLevel = struct.unpack('<H', BatBuff[-2:])[0]
    BatBuff = BatBuff[:-2]
    if BatBuff != PackBatteryCfg():
      VBat_OverLevel, VBat_ReadyLevel, VBat_CritLevel, VBat_OffLevel, IChg_BulkLevel, IChg_FloatLevel = struct.unpack('<HHHHHH', BatBuff)
      Config.SetKey('Battery', 'Overvoltage', VBat_OverLevel)
      Config.SetKey('Battery', 'Autostart', VBat_ReadyLevel)
      Config.SetKey('Battery', 'Critical', VBat_CritLevel)
      Config.SetKey('Battery', 'Disconnected', VBat_OffLevel)
      Config.SetKey('Battery', 'ChgBulk', IChg_BulkLevel)
      Config.SetKey('Battery', 'ChgFloat', IChg_FloatLevel)
      if DebugI2C: print('Battery settings updated.')
    else: 
      if DebugI2C: print('Received the same Battery settings.') 
    return True
  except: return False   

def SaveBatLow():
  try:
    OldBatLow = Config.GetIntKey('Battery', 'LowBat', 0)
    if VBat_LowLevel != OldBatLow:
      Config.SetKey('Battery', 'LowBat', VBat_LowLevel)
      if DebugI2C: print('LowBat Level setting updated.')
  except:
    if DebugI2C: print('Error while saving BatLow !')  


#------ ADC Functions --------------------------

def GetVbat():
  if BatTest > 0: return int(BatTest * 1000)  
  Raw = (VbatADC.read_u16() >> 4) & 0xFFF
  Raw = Raw - ADC_Offset
  if Raw < 0: Raw = 0
  return int(Raw * VBat_Step * 1000)

def GetVps():
  Raw = (VpsADC.read_u16() >> 4) & 0xFFF
  Raw = Raw - ADC_Offset
  if Raw < 0: Raw = 0
  return int(Raw * VPS_Step * 1000)

def GetIchg():
  Raw = (IchgADC.read_u16() >> 4) & 0xFFF
  Raw = Raw - ADC_Offset - OPA_Offset
  if Raw < 0: Raw = 0
  mVolt = Raw * ADC_Step * 1000
  mAmp = (mVolt * IChg_Ratio) - IChg_Other
  if mAmp < 0: mAmp = 0
  return int(mAmp)

def GetVsys():
  Raw = (Vsys.read_u16() >> 4) & 0xFFF
  #Raw = Raw - ADC_Offset
  if Raw < 0: Raw = 0
  return int(Raw * VSys_Step * 1000)


#------ Async Coros ---------------------

async def PowerOff(autost=True, alarm=True):
  if CanPowerOff(): SaveGraphs()
  if alarm:
    if not CanPowerOff():
      if OnUSB(): print('PowerOff failed !')  
      return False
    await ShutdownAlert(3)
  if CanPowerOff():
    if autost and not AutoStart(): SetAutoStart()  
    OutSwitch.off(); BatSwitch.off()  
    Pin(pinPwrOff, Pin.OUT, value=1)  
    time.sleep(5)
    if OnUSB(): print('--- The End ---')
    return True # if this returns, something is not right
  else:
    if OnUSB(): print('PowerOff failed !')  
    return False

async def ShutdownAlert(N):
  global StLUpdate
  SNE = SoundEn
  async with BuzzLock:
    if SNE:  
      BuzON = Duty(50)
      Buzzer.init(freq=1000)
    StLUpdate = False
    StLed.state(StatLed.Off)
    if SNE: Buzzer.duty_u16(BuzOFF)
    await asyncio.sleep(0.8)
    try:
      for i in range(N):
        if SNE: Buzzer.duty_u16(BuzON)
        StLed.toggle(StatLed.Green)  
        await asyncio.sleep_ms(200)
        if SNE: Buzzer.duty_u16(BuzOFF)
        StLed.toggle(StatLed.Green)  
        await asyncio.sleep(1)
      StLed.state(StatLed.Red)
      if SNE: Buzzer.duty_u16(BuzON)
      time.sleep(1.5)
    except asyncio.CancelledError:
      pass
    finally:
      if SNE: Buzzer.duty_u16(BuzOFF)
      StLed.state(StatLed.Off)
      StLUpdate = True


#------ Main Async Tasks ---------------------

async def TermWait(secs):
  while secs > 0:
    await asyncio.sleep(1); secs -= 1
    if Terminated: return True
  return False

async def PowerWatchTask():
  global REG_Vbat, REG_Vps, REG_Vsys, REG_Ichg, REG_Power, REG_Battery, REG_Shutdown, REG_BatOver
  global PwrON, BatON, IsrBatCrit, BCTRunning, IsrBatLow, BLTRunning, BatFull, LowBatWarned
  global VbatAVG, VpsAVG, IchgAVG, VsysAVG, ResetBat, ResetPS, StartWhenReady, UpdAlert

  def BatGood(): return REG_Vbat > VBat_LowLevel

  TaskEnter('PowerWatch')
  try:
    while not Terminated:
      #TS = time.ticks_us()
      
      if ResetPS:
        ResetPS = False; UpdAlert = True
        VpsAVG.reset(); VbatAVG.reset(); IchgAVG.reset()
      if ResetBat:
        ResetBat = False; UpdAlert = True  
        VbatAVG.reset(); IchgAVG.reset()  
       
      VP = GetVps() 
      NewPwrON = VP > VPS_OffLevel
      if NewPwrON != PwrON:
        PwrON = NewPwrON
        ResetPS = True
        if PwrON:
          REG_Power = stPowerON  
          if SoundEn: AsyncAddCmd(tcBeep)
          if DebugADC: print('--- PS connected ---')
        else:
          REG_Power = stPowerOFF  
          if SoundEn: LostPowerBuzz(3)  
          if DebugADC: print('--- PS disconnected ---')
      VpsAVG.add_data(VP);  REG_Vps = VpsAVG.get_avg()
      
      VB = GetVbat()
      NewBatON = VB > VBat_OffLevel
      if NewBatON != BatON:
        BatON = NewBatON
        ResetBat = True
        if BatON:
          REG_Battery = stBatON  
          if SoundEn: AsyncAddCmd(tcBeep)
          if DebugADC: print('--- Battery connected ---')
        else:
          REG_Battery = stBatOFF  
          if SoundEn: LostBatBuzz(3)  
          if DebugADC: print('--- Battery disconnected ---')
      VbatAVG.add_data(VB); REG_Vbat = VbatAVG.get_avg()
      
      if REG_BatOver == stBatOver:
        if REG_Vbat <= (VBat_OverLevel - VBat_OverHyst):
          REG_BatOver = stNone; UpdAlert = True  
          if DebugADC: print('Battery overvoltage cleared.')
      else:
        if REG_Vbat >= (VBat_OverLevel + VBat_OverHyst):
          REG_BatOver = stBatOver; UpdAlert = True  
          if DebugADC: print('Warning: Battery overvoltage !')
          
      if StartWhenReady and (BAuto.value() == 0) and (REG_Vbat >= VBat_ReadyLevel):
        OutSwitch.on()
        StartWhenReady = False

      VS = GetVsys(); VsysAVG.add_data(VS); REG_Vsys = VsysAVG.get_avg()
      IC = GetIchg(); IchgAVG.add_data(IC); REG_Ichg = int(IchgAVG.get_avg())
      if BatFull:
        if REG_Ichg >= (IChg_FloatLevel + IChg_FloatHyst): BatFull = False
      else:  
        if REG_Ichg <= (IChg_FloatLevel - IChg_FloatHyst): BatFull = True
            
      UpdateStatLed()

      if DebugADC:
        fVps  = float(REG_Vps)  / 1000
        fVbat = float(REG_Vbat) / 1000
        fVsys = float(REG_Vsys) / 1000
        print(f'V.PS[{int(PwrON)}]: {fVps:.2f} V   V.Bat[{int(BatON)}]: {fVbat:.2f} V   Bat.Chg: {REG_Ichg} mA   V.SYS: {fVsys:.3f} V')

      if LowBatWarned and BatGood():
        REG_Shutdown = stNone; UpdAlert = True
        if DebugADC: print('Battery good: NAS signaled to abort.')

      if IsrBatCrit:
        IsrBatCrit = False  
        if (OutSwitch.value() == 0) or (NasOn.value() == 0):
          if DebugADC: print('Battery Critical: Powering off...')
          await PowerOff()
        else:
          if NasInShd:
            if DebugADC: print(f'Battery Critical: NAS is shutting down. Waiting {CritShdWait}s ...')    
            if await TermWait(CritShdWait): return
            if DebugADC: print('Powering off...')
          else:     
            REG_Shutdown = stShdNow; UpdateNasAlert(True)
            if DebugADC: print('Battery Critical: NAS signaled to shutdown now !') 
            if await TermWait(CritAckWait): return
            if NasAlert.value() == 0:
              if DebugADC: print(f'NAS acknowledged. Waiting {CritShdWait}s for it to shutdown...')   
              if await TermWait(CritShdWait): return
              if DebugADC: print('Powering off...')   
            else:
              if DebugADC: print('NAS not responding. Powering off anyway...')   
          await PowerOff()

      if IsrBatLow:
        IsrBatLow = False  
        if (OutSwitch.value() == 0) or (NasOn.value() == 0):
          if DebugADC: print('Battery Low: Trying to shutdown...')
          await PowerOff()
        else:
          if REG_Shutdown == stNone:  
            REG_Shutdown = stShdLow; UpdAlert = True
            if DebugADC: print('Battery Low: NAS signaled to shutdown.')
          else:
            if DebugADC: print('Battery still Low.')
        
      if not BCTRunning and BatON and (REG_Vbat <= VBat_CritLevel) and not ResetBat:
        BatCrtTimer.init(period=(BCrtTime*1000), mode=Timer.ONE_SHOT, callback=CriticalISR)
        BCTRunning = True
        if DebugADC: print('Critical Timer started')
      if not BLTRunning and BatON and not BatGood() and not ResetBat:
        BatLowTimer.init(period=(BLowTime*1000), mode=Timer.ONE_SHOT, callback=LowBatISR)
        BLTRunning = True
        if DebugADC: print('LowBat Timer started')
      
      if BCTRunning and (not BatON or (REG_Vbat > VBat_CritLevel)):
        BatCrtTimer.deinit()
        BCTRunning = False
        if DebugADC: print('Critical Timer stopped')
      if BLTRunning and (not BatON or BatGood() ):
        BatLowTimer.deinit()
        BLTRunning = False
        if DebugADC: print('LowBat Timer stopped')

      if UpdAlert:
        UpdateNasAlert(True); UpdAlert = False
        if REG_Shutdown == stShdLow: LowBatWarned = True
        if REG_Shutdown == stNone: LowBatWarned = False

      # print('Time =', time.ticks_us() - TS) 
      await asyncio.sleep(PowerTask_time)
  except asyncio.CancelledError: pass
  finally: TaskExit('PowerWatch')


async def TemperatureTask():
  global REG_Duty, REG_RPM, REG_TMP
  TaskEnter('Temperature')
  try:
    while not Terminated:
      REG_RPM = round(RPM.GetFreq()*30)
      REG_TMP = TmpSensor.Temperature()
      DC = round(FanDutyCycle(REG_TMP))
      if FanAuto: DC = FilterDC(DC, 5)
      if not SoundEn and DC > MaxFDuty: DC = MaxFDuty
      if DC != REG_Duty:
        REG_Duty = DC  
        FanPWM.duty_u16(Duty(REG_Duty))
      if DebugTMP:
        ftmp = float(REG_TMP) / 100  
        print(f'Temp = {ftmp:.2f}°C   RPM = {REG_RPM}   Duty = {REG_Duty}%')
      await asyncio.sleep(TempTask_time)
  except asyncio.CancelledError: pass
  finally: TaskExit('Temerature')


async def TimerTask():
  global VIcounter, TDcounter, SEcounter, OFcounter, RScounter, SoundEn
  global BStart_LPT, BStop_LPT, Usb_LCT  
  TaskEnter('Timer')
  try:
    while not Terminated:
      if VIcounter >= 60:
        AddBatVI(REG_Vbat, REG_Ichg)
        VIcounter = 0
      if TDcounter >= 60:     
        AddTerm(REG_TMP, REG_Duty)
        TDcounter = 0
      if SEcounter >= 60:
        SoundEn = GetSoundEn()
        SEcounter = 0
      if OFcounter >= 3600:
        CurrTime = time.ticks_ms()
        BStart_LPT = CurrTime
        BStop_LPT  = CurrTime
        Usb_LCT    = CurrTime
        OFcounter = 0  
      await asyncio.sleep(1)
      if RScounter > 0:
        RScounter -= 1
        if RScounter <= 0:
          if REG_Vbat <= VBat_LowLevel:
            AsyncAddCmd(tcError)
          else:            
            OutSwitch.on()  
            AsyncAddCmd(tcBeep)
      VIcounter += 1; TDcounter += 1; SEcounter += 1; OFcounter += 1;
  except asyncio.CancelledError: pass
  finally: TaskExit('Timer')
  

async def I2CSlaveTask():
  global ClockSynced, REG_Shutdown, REG_Duty, RScounter, SoundEn, VBat_LowLevel, NasInShd  
  TaskEnter('I2CSlave')  
  try:
    while not Terminated:
      Reg = NasI2C.ReadDataByte()
      
      if Reg == regCMD:  # Command Register
        CMD = NasI2C.ReadDataBlock16(4)
        if CMD == cmdRstReady:
          RSecs = struct.unpack('<H', NasI2C.ReadDataBlock16(2))[0]
          if RSecs < 10: RSecs = 10
        
        if (CMD == cmdRstReady) or (CMD == cmdShdReady) or (CMD == cmdPowerOff):
          if DebugI2C: print('NAS is ready to power off !')
          OutSwitch.off(); NasInShd = False
          if (REG_Shutdown == stShdLow) or (CMD == cmdPowerOff): await PowerOff()
          else: AsyncAddCmd(tcBeep)
          REG_Shutdown = stNone
          if CMD == cmdRstReady:
            RScounter = RSecs
            if DebugI2C: print(f'Re-Start in {RSecs} seconds')
          
        elif CMD == cmdReadBat:
          if DebugI2C: print('Sending Battery buff...')
          Sent = SendI2CBuff(BatVIBuff)
          if DebugI2C:
            if Sent: print('Done !')
            else: print('Failed !')    

        elif CMD == cmdReadTerm:
          if DebugI2C: print('Sending Termal buff...')
          Sent = SendI2CBuff(TermBuff)
          if DebugI2C:
            if Sent: print('Done !')
            else: print('Failed !')    

        else:
          if DebugI2C: print(f'Unknown command: {FormatBytes(CMD)}')

      elif Reg == regMain:  # Main Registers
        blk = struct.pack('<HHHHHBH', REG_Vbat, REG_Vps, REG_Vsys, REG_Ichg, REG_RPM, REG_Duty, REG_TMP)  
        NasI2C.SendDataBlock32(blk)
        # if DebugI2C: print('Status read.')

      elif Reg == regAlert:  # Alert Registers
        NasI2C.SendDataBlock32(REG_Shutdown + REG_Power + REG_Battery + REG_BatOver)
        UpdateNasAlert(False)
        if DebugI2C: print('Alert handled.')
      
      elif Reg == regFanCfg:  # Fan Config Register
        FanBuff = NasI2C.ReadDataBlock16(11, 50)
        if len(FanBuff) == 11:
          SetFanConfig(FanBuff)
        else: 
          if DebugI2C: print('I2C Error: FanCfg !')
          
      elif Reg == regSilentCfg:  # Silent Config Register
        SilBuff = NasI2C.ReadDataBlock16(11, 50)
        if len(SilBuff) == 11:
          SetSilentConfig(SilBuff)
        else:
          if DebugI2C: print('I2C Error: SilentCfg !')

      elif Reg == regBatCfg:  # Battery Config Register
        BatBuff = NasI2C.ReadDataBlock16(14, 50)
        if len(BatBuff) == 14:
          SetBatteryConfig(BatBuff)
        else:  
          if DebugI2C: print('I2C Error: BatCfg !')

      elif Reg == regBatLow:  # Battery Low Level Register
        BatBuff = NasI2C.ReadDataBlock16(2, 50)
        if len(BatBuff) == 2:
          VBat_LowLevel = struct.unpack('<H', BatBuff)[0]
          if DebugI2C: print(f'New BatLow: {VBat_LowLevel}')
        else:  
          if DebugI2C: print('I2C Error: BatLow !')

      elif Reg == regRTC:  # Set RTC Register
        packedDT = NasI2C.ReadDataBlock16(9)
        if len(packedDT) == 9:
          PicoRTC.datetime(struct.unpack('<HBBBBBBB', packedDT))
          ClockSynced = True; RTCSync.on()
          SoundEn = GetSoundEn()
          if not SoundEn and REG_Duty > MaxFDuty:
            REG_Duty = MaxFDuty
            FanPWM.duty_u16(Duty(REG_Duty))
          RestoreGraphs()  
          if DebugI2C: print('RTC set.')
        else:  
          if DebugI2C: print('I2C Error: Setting RTC !')

      elif Reg == regShdState:  # NAS Shutdown State Register
        BState = NasI2C.ReadDataByte()
        if   BState == b'\x01': NasInShd = False
        elif BState == b'\x02': NasInShd = True

      if NasI2C.ReadRequest(): NasI2C.SendNone()  
      await asyncio.sleep(I2CTask_time)
  except asyncio.CancelledError: pass
  finally: TaskExit('I2CSlave')


async def InputTask():
  global InputRunning, DebugADC, DebugBTN, DebugTMP, DebugI2C, DebugRTC, BatTest
  TaskEnter('Input')
  InputRunning = True; UsbON = True; rtc_count = 8
  poll_obj = select.poll()  
  poll_obj.register(sys.stdin, select.POLLIN)
  while poll_obj.poll(0): sys.stdin.read(1) # discard all 
  try:
    while not Terminated and UsbON:
      if poll_obj.poll(0):  
        cmd = ''
        while True:
          ch = sys.stdin.read(1)
          if ch == '\n':
            #sys.stdin.read(1)
             break
          else:
            if (ord(ch) >= 0x20) and (ord(ch) <= 0x7E): cmd += ch
        cmd, param = SplitInputCmd(cmd)
        
        if cmd == 'exit':
          print('Terminate command received.')
          TerminateProgram(); break
          
        elif cmd == 'endinput': break

        elif cmd == 'low':
          print(f'VBat Low Level = {VBat_LowLevel/1000} V')
          
        elif cmd == 'info':
          print('--- System Info ---')
          gc.collect()
          mfree = gc.mem_free(); mused = gc.mem_alloc()
          fs_info = os.statvfs('/'); fs_size = fs_info[1] * fs_info[2]; fs_free = fs_info[0] * fs_info[3]
          print(f'RAM:    [ Total: {mfree+mused} bytes ] = [ Free: {mfree} bytes ] + [ Used: {mused} bytes ]')            
          print(f'Flash:  [ Total: {fs_size} bytes ] = [ Free: {fs_free} bytes] + [ Used: {fs_size-fs_free} bytes ]')
          
        elif cmd == 'adc':
          DebugADC = not DebugADC
          print('adc: ON') if DebugADC else print('adc: OFF')
        elif cmd == 'btn':
          DebugBTN = not DebugBTN
          print('btn: ON') if DebugBTN else print('btn: OFF')
        elif cmd == 'tmp':
          DebugTMP = not DebugTMP
          print('tmp: ON') if DebugTMP else print('tmp: OFF')
        elif cmd == 'i2c':
          DebugI2C = not DebugI2C
          print('i2c: ON') if DebugI2C else print('i2c: OFF')
        elif cmd == 'rtc':
          DebugRTC = not DebugRTC
          print('rtc: ON') if DebugRTC else print('rtc: OFF')
          if DebugRTC:
            rtc_count = 8
            PrintTime()
        
        elif cmd == 'fan':
          if param == None: print('< bad param >')
          else:
            print(f'New FAN duty: {param}%') 
            FanPWM.duty_u16(Duty(param))
          
        elif cmd == 'bat':
          if param == None: print('< bad param >')
          else:
            if param == 0: print('Bat released.')  
            else: print(f'Bat override: {param}V')  
            BatTest = param
                    
        elif cmd == '': pass
        else: print(f'< unknown command [{cmd}] >')
              
      await asyncio.sleep(InputTask_time)
      
      if DebugRTC:
        rtc_count -= 1
        if rtc_count == 0:
          rtc_count = 8
          PrintTime()
          
      UsbON = OnUSB()
  except asyncio.CancelledError: pass
  finally:
    DebugADC = False; DebugBTN = False
    DebugTMP = False; DebugI2C = False
    DebugRTC = False
    InputRunning = False
    if not UsbON: AsyncAddCmd(tcBeep)
    TaskExit('Input')


async def AsyncCMDTask():
  global CmdBuff, idxAdd
  TaskEnter('AsyncCMD')
  for i in range(len(CmdBuff)): CmdBuff[i] = 0
  idxAdd = 0; idxExec = 0; AsyncCMD.clear()
  try:
    while not Terminated:
      await AsyncCMD.wait()
      while not Terminated and (CmdBuff[idxExec] > 0):
        TaskCMD = CmdBuff[idxExec]
        #print(f'{idxExec} = {TaskCMD}')
        
        if TaskCMD == tcStTimer: StartTimer.init(period=200, mode=Timer.ONE_SHOT, callback=StartTimerISR)
        elif TaskCMD == tcSp1Timer: StopTimer.init(period=200, mode=Timer.ONE_SHOT, callback=StopTimer1ISR)
        elif TaskCMD == tcSp2Timer: StopTimer.init(period=2000, mode=Timer.ONE_SHOT, callback=StopTimer2ISR)
        elif TaskCMD == tcUsbTimer: UsbTimer.init(period=500, mode=Timer.ONE_SHOT, callback=USBTimerISR)
        
        elif TaskCMD == tcBeep:
          if not BuzzLock.locked():
            async with BuzzLock:
              BuzON = Duty(2);
              Buzzer.init(freq=1000)
              try:
                Buzzer.duty_u16(BuzON) 
                await asyncio.sleep_ms(50)
              finally:
                Buzzer.duty_u16(BuzOFF)
              
        elif TaskCMD == tcError:
          if not BuzzLock.locked():
            async with BuzzLock:
              BuzON = Duty(0.8);
              Buzzer.init(freq=200)
              try:
                Buzzer.duty_u16(BuzON) 
                await asyncio.sleep_ms(200)
              finally:
                Buzzer.duty_u16(BuzOFF)
                
        elif TaskCMD == tcInput:
          if not InputRunning:
            TaskList.append(asyncio.create_task(InputTask()))
            AsyncAddCmd(tcBeep)
                
        CmdBuff[idxExec] = 0
        idxExec += 1;
        if idxExec == 16: idxExec = 0      
        if CmdBuff[idxExec] == 0:
          AsyncCMD.clear()
          break
        else: await asyncio.sleep(0)
  except asyncio.CancelledError: pass
  finally: TaskExit('AsyncCMD')

def AsyncAddCmd(cmd):
  global idxAdd  
  if CmdBuff[idxAdd] == 0:    
    CmdBuff[idxAdd] = cmd
    idxAdd += 1
    if idxAdd == 16: idxAdd = 0
    AsyncCMD.set()


async def BoardLEDTask():
  TaskEnter('BoardLed')  
  try:
    while not Terminated:
      BoardLed.value(not BoardLed.value())
      await asyncio.sleep(BoardTask_time)
  except asyncio.CancelledError: pass
  finally: TaskExit('BoardLed')


#------ Aux Task Launchers ----------------------

def LostPowerBuzz(N):
  TaskList.append(asyncio.create_task(LostPowerBuzzTask(N)))

def LostBatBuzz(N):
  TaskList.append(asyncio.create_task(LostBatBuzzTask(N)))


#------ Aux Async Tasks -------------------------

async def LostPowerBuzzTask(N):
  async with BuzzLock:  
    BuzON = Duty(50); Buzzer.init(freq=3800)
    try:
      for i in range(N):
        Buzzer.duty_u16(BuzON)
        await asyncio.sleep_ms(120)
        Buzzer.duty_u16(BuzOFF)
        await asyncio.sleep_ms(100)
        Buzzer.duty_u16(BuzON)
        await asyncio.sleep_ms(250)
        if i < (N-1):
          Buzzer.duty_u16(BuzOFF)
          await asyncio.sleep(1)
    except asyncio.CancelledError: pass
    finally:
      Buzzer.duty_u16(BuzOFF)
      TaskExit()

async def LostBatBuzzTask(N):
  async with BuzzLock:  
    BuzON = Duty(50); Buzzer.init(freq=3800)
    try:
      for i in range(N):
        Buzzer.duty_u16(BuzON)
        await asyncio.sleep_ms(370)
        if i < (N-1):
          Buzzer.duty_u16(BuzOFF)
          await asyncio.sleep_ms(250)
    except asyncio.CancelledError: pass
    finally: 
      Buzzer.duty_u16(BuzOFF)
      TaskExit()


#----- Main Async Coro ---------------  

async def main():
  global TaskList, Terminated
  loop = asyncio.get_event_loop()
  loop.set_exception_handler(HandleAsyncExceptions)  
  TaskList = []; AllTasksDone.clear(); Terminated = False   
  TaskList.append(asyncio.create_task(BoardLEDTask()))
  TaskList.append(asyncio.create_task(I2CSlaveTask()))
  TaskList.append(asyncio.create_task(PowerWatchTask()))
  TaskList.append(asyncio.create_task(TemperatureTask()))
  TaskList.append(asyncio.create_task(TimerTask()))
  TaskList.append(asyncio.create_task(AsyncCMDTask()))
  if OnUSB(): TaskList.append(asyncio.create_task(InputTask()))
  await AllTasksDone.wait()
  if OnUSB(): print('Main Program gracefully terminated.')

def HandleAsyncExceptions(loop, context):
  if OnUSB():
    print(LineBreak)
    sys.print_exception(context['exception'])
    print(LineBreak)
  else:
    with open('/exceptions.txt', 'a') as LogFile:
      DT = PicoRTC.datetime()
      TimeStamp = '[ {:02d}-{:02d}-{:04d}, {:02d}:{:02d}:{:02d} ]'.format(DT[2], DT[1], DT[0], DT[4], DT[5], DT[6])  
      LogFile.write(LineBreak+'\n')
      LogFile.write(TimeStamp+'\n')
      LogFile.write(LineBreak+'\n')
      sys.print_exception(context['exception'], LogFile)
  TerminateProgram()
  
def TaskEnter(name=''):
  if OnUSB() and (name != ''): print(f'Task: {name} started')    
    
def TaskExit(name=''):
  CT = asyncio.current_task()
  if CT in TaskList: TaskList.remove(CT)    
  if len(TaskList) == 0: AllTasksDone.set()
  if OnUSB() and (name != ''): print(f'Task: {name} ended')    

def TerminateProgram():
  global Terminated
  Terminated = True
  AsyncCMD.set()

#====== Entry Point ===================================

USBPower  = Pin(pinUSB, Pin.IN) 
if OnUSB(): print('Starting...')  

# Configure GPIO pins

Buzzer    = PWM(Pin(pinBuzz), duty_u16=0)
FanPWM    = PWM(Pin(pinFanPWM), freq=25000, duty_u16=0)
FanRPM    = Pin(pinFanRPM, Pin.IN, Pin.PULL_UP)

BAuto     = Pin(pinBAuto, Pin.IN, Pin.PULL_UP)
BStart    = Pin(pinBStart, Pin.IN, Pin.PULL_UP); 
BStop     = Pin(pinBStop, Pin.IN, Pin.PULL_UP)

BoardLed  = Pin(pinBrdLed, Pin.OUT, value=1)
OutSwitch = Pin(pinOutSw, Pin.OUT)   # default state !!
BatSwitch = Pin(pinBatSw, Pin.OUT, value=0)
StLed     = StatLed(pinGrnLed, pinRedLed)
RTCSync   = Pin(pinRTCSync, Pin.OUT) # default state !!

VbatADC   = ADC(Pin(pinVBat))
VpsADC    = ADC(Pin(pinVPS))
IchgADC   = ADC(Pin(pinIChg))
Vsys      = ADC(Pin(pinVsys))

NasI2C    = I2CSlave(0, sda=pinNasSda, scl=pinNasScl, slaveAddr=0x41) 
NasAlert  = Pin(pinNasAlert, Pin.OUT, value=0)
NasOn     = Pin(pinNasOn, Pin.IN, Pin.PULL_DOWN)

AuxI2C    = I2C(1, scl=Pin(pinAuxScl), sda=Pin(pinAuxSda), freq=100000)
AuxAlert  = Pin(pinAuxAlert, Pin.IN, Pin.PULL_UP)

# Init global variables

DebugADC        = False
DebugBTN        = False
DebugTMP        = False
DebugI2C        = False
DebugRTC        = False

Terminated      = False                     # program terminated flag
TaskList        = []                        # the list of started Tasks
AllTasksDone    = asyncio.ThreadSafeFlag()  # signal when all task are terminated

CmdBuff         = bytearray(16)             # command buffer
idxAdd          = 0                         # the index where to add the new command
AsyncCMD        = asyncio.ThreadSafeFlag()  # start executing commands

InputRunning    = False                     # tells when the Input Task is running
Usb_LCT         = 0                         # last USB connect/disconnect
UsbTimer        = None                      # USB debouncing timer

BatFull         = False                     # indicate that the charging current is under IChg_FloatLevel
IsrBatCrit      = False                     # battery critical flag (set by ISR / cleared when handled)
IsrBatLow       = False                     # battery low flag (set by ISR / cleared when handled)
UpdAlert        = False                     # update NAS alert
LowBatWarned    = False                     # if set, the Low Battery warning was sent
ResetBat        = False                     # reset battery average buffers   
ResetPS         = False                     # reset power supply average buffers
StartWhenReady  = False                     # was shutdown by low bat
NasInShd        = False                     # if set, NAS is executing the shutdown sequence 
VbatAVG         = AverageInt(6)             # battery voltage average buffer 
IchgAVG         = AverageInt(6)             # battery charging current average buffer
VpsAVG          = AverageInt(6)             # power supply voltage average buffer
VsysAVG         = AverageInt(6)             # VSYS voltage average buffer

BatVIBuff       = bytearray(5762)           # last 24 hours Bat V*I / mV, 2-byte, 1 min / 2880 + 2880 + 2
Pstart          = len(BatVIBuff)-2          # position start index
Istart          = Pstart // 2               # current start index
VIcounter       = 0                         # number of seconds since last update

TermBuff        = bytearray(5762)           # last 24 hours Term Tmp*DC / 0.00 *C, 2-byte, 1 min / 2880 + 2880 + 2
Qstart          = len(TermBuff)-2           # position start index
Dstart          = Qstart // 2               # duty cycle start index
TDcounter       = 0                         # number of seconds since last update

BCTRunning      = False                     # battery critical timer running flag  
BLTRunning      = False                     # battery low timer running flag
BatCrtTimer     = None                      # battery critical timer
BatLowTimer     = None                      # battery low timer

BStart_LPT      = 0                         # Start button last pressed time
BStop_LPT       = 0                         # Stop button last pressed time
StartTimer      = None                      # Start button debouncing timer     
StopTimer       = None                      # Stop button debouncing timer

BuzOFF          = 0                         # duty cycle of Buzzer off state (constant)
BuzzLock        = asyncio.Lock()            # async buzzer access lock

PicoRTC         = RTC()                     # system RTC
ClockSynced     = bool(RTCSync.value())     # tells if RTC is synchronized

SoundEn         = True                      # sound enable (not silent mode)
SEcounter       = 0                         # number of seconds since last SoundEn read     

RPM             = None                      # the RPM pulse counter object
StLUpdate       = True                      # status led update enabled
LineBreak       = 40 * '-'                  # log separator (constant)
FanOFF          = 0                         # duty cycle of FAN off state (constant)
BatTest         = 0                         # used for debuging (overrides the battery voltage)
OFcounter       = 0                         # number of seconds since last anti-overflow adjustment
RScounter       = 0                         # countdown until re-start
GraphsHandled   = False                     # tells if the restoration of BatVIBuff and TermBuff was handled

try:
  # Starting the program with a delay for ADC voltage to stabilize
  time.sleep_ms(600)
  
  # Read custom settings
  Config = ConfigFile(IniFile, DefaultSettings)

  FanAuto  = Config.GetBoolKey('Fan', 'Auto', True)          #  flag
  LowTemp  = Config.GetIntKey('Fan', 'LowTemp', 3150)        #  1/100 *C
  HighTemp = Config.GetIntKey('Fan', 'HighTemp', 3350)       #  1/100 *C 
  LowDuty  = Config.GetIntKey('Fan', 'LowDuty', 20)          #  %
  HighDuty = Config.GetIntKey('Fan', 'HighDuty', 100)        #  %
  FixDuty  = Config.GetIntKey('Fan', 'FixDuty', 35)          #  % 
  DPG = (HighDuty - LowDuty) / (HighTemp - LowTemp)

  SilentMode = Config.GetBoolKey('Silent', 'Enabled', True)  # Silent Mode - enabled
  SilentSTH  = Config.GetIntKey('Silent', 'StartHour', 22)   # Silent Mode - start hour       
  SilentSTM  = Config.GetIntKey('Silent', 'StartMin', 30)    # Silent Mode - start minute
  SilentSPH  = Config.GetIntKey('Silent', 'StopHour', 8)     # Silent Mode - stop hour
  SilentSPM  = Config.GetIntKey('Silent', 'StopMin', 0)      # Silent Mode - stop minute
  MaxFDuty   = Config.GetIntKey('Silent', 'MaxFDuty', 40)    # Silent Mode - max fan duty 

  VBat_OverLevel  = Config.GetIntKey('Battery', 'Overvoltage', 13900)    # milivolts   / overvoltage - give warning
  VBat_ReadyLevel = Config.GetIntKey('Battery', 'Autostart', 12500)      # milivolts   / autostart ready - start UPS if it was shutdown by Low Bat 
  VBat_LowLevel   = Config.GetIntKey('Battery', 'LowBat', 11800)         # milivolts   / low battery - ask nicely to shutdown
  VBat_CritLevel  = Config.GetIntKey('Battery', 'Critical',11500)        # milivolts   / critical battery - perform forced shutdown
  VBat_OffLevel   = Config.GetIntKey('Battery', 'Disconnected', 5000)    # milivolts   / disconnected battery
  IChg_BulkLevel  = Config.GetIntKey('Battery', 'ChgBulk', 900)          # miliamps    / bulk current charging stage [min]
  IChg_FloatLevel = Config.GetIntKey('Battery', 'ChgFloat', 10)          # miliamps    / battery is fully charged [max]
 
  # Init Power states
  PwrON = GetVps() > VPS_OffLevel
  BatON = GetVbat() > VBat_OffLevel
  REG_Power = stPowerON if PwrON else stPowerOFF
  REG_Battery = stBatON if BatON else stBatOFF
  REG_BatOver = stBatOver if GetVbat() >= VBat_OverLevel else stNone
  BatFull = GetIchg() <= IChg_FloatLevel
  StartWhenReady = AutoStart()
  if StartWhenReady: ClearAutoStart()

  # If battery si LOW, power down the device
  if (GetVbat() <= VBat_LowLevel) and CanPowerOff(): PowerOffExit()

  # Mark program start
  if OnUSB(): print('Main Program started. Firmware v1.0')
  WellcomeBuzz()
  
  # Powering up what is needed
  BatSwitch.on(); time.sleep_ms(400)  # delay to stabilize the IChg

  # Setup TMP275 sensor
  TmpSensor = TMP275(AuxI2C, 0x4F, 12)
  #TmpSensor.SetTempAlert(TMP275.tlow_reg, 23)
  #TmpSensor.SetTempAlert(TMP275.thig_reg, 24)
  TmpSensor.SetPointer(TMP275.temp_reg)  

  # Create timers for ON/OFF buttons and setup related registers
  StartTimer = Timer(); StopTimer = Timer()
  BStart_LPT = time.ticks_ms(); BStop_LPT = BStart_LPT
  BStart.irq(trigger=Pin.IRQ_FALLING, handler=StartISR)
  BStop.irq(trigger=Pin.IRQ_FALLING, handler=StopISR)

  # Create timers for Battery State and setup related registers
  BatCrtTimer = Timer(); BatLowTimer = Timer()

  # Setup USB pin monitor
  Usb_LCT = time.ticks_ms()
  UsbTimer = Timer()
  USBPower.irq(trigger=Pin.IRQ_RISING, handler=USBPowerISR)

  # Fan RPM initializations
  RPM = PulseCounter(0, FanRPM)
  
  # Restore saved graphs buffers if they are available 
  RestoreGraphs()
  
  # Init silent mode
  SoundEn = GetSoundEn()
  
  #----- Main Loop -----
  while not Terminated:
    try:
      asyncio.new_event_loop()
      asyncio.run(main())
    except KeyboardInterrupt:
      if OnUSB(): print('----- Soft Reset -----')
    except Exception as E:
      if OnUSB():
        print(LineBreak)  
        sys.print_exception(E)  
        print(LineBreak)
      else:
        with open('/exception_log.txt', 'a') as LogFile:
          DT = PicoRTC.datetime()
          TimeStamp = '[ {:02d}-{:02d}-{:04d}, {:02d}:{:02d}:{:02d} ]'.format(DT[2], DT[1], DT[0], DT[4], DT[5], DT[6])  
          LogFile.write(LineBreak+'\n')
          LogFile.write(TimeStamp+'\n')
          LogFile.write(LineBreak+'\n')
          sys.print_exception(E, LogFile)
      time.sleep(2)
  #-----------------------    
      
finally:
  if OnUSB(): print('Cleaning up...')
  
  # Saving data...
  SaveGraphs()  # Trying to save BatVIBuff and TermBuff data
  SaveBatLow()  # Save BatLowLevel config if changed
  
  # Unregister IRQ handlers
  BStart.irq(handler=None)
  BStop.irq(handler=None)
  USBPower.irq(handler=None)
  
  # Stop timers
  if StartTimer  != None: StartTimer.deinit()
  if StopTimer   != None: StopTimer.deinit()
  if BatCrtTimer != None: BatCrtTimer.deinit()
  if BatLowTimer != None: BatLowTimer.deinit()
  if UsbTimer    != None: UsbTimer.deinit()
  
  # Release I2C Slave
  NasI2C.deinit()
  
  # Stop RPM pulse counter
  if RPM != None: RPM.deinit()
  
  # Stop PWMs
  FanPWM.duty_u16(FanOFF); Buzzer.duty_u16(BuzOFF);
  time.sleep_ms(10); FanPWM.deinit(); Buzzer.deinit()
  
  # Powering down what is not needed
  BatSwitch.off(); StLed.state(StatLed.Off); BoardLed.on()
  
  # Free resources
  TaskList = None; BuzzLock = None;
  Config.Close()

  if OnUSB(): print('All done !')


# --------------------- TO DO: ---------------------------------
# 
#  Bugs:
#
#
#  Improvements:
#   - make the I2C slave to run on interrupts instead of pulling
#
#
#  New features:
#
#
#  To check:
#   - what happens if I press both buttons at once ?
#   - what happens if USB power is connected and Pico is forced to start
#
#---------------------------------------------------------------

