import usb.core
import usb.util
import time
import numpy as np

class NanoDrop1000:
    # USB Constants
    VID = 0x2457
    PID = 0x1002
    EP_OUT = 0x02       # Command Mailbox
    EP_IN_HEAVY = 0x82  # Spectrum Data Mailbox (4096 bytes)
    EP_IN_COMM = 0x87   # Text/Status Mailbox (64 bytes)

    def __init__(self):
        self.dev = None
        self.coefficients = {}
        self.wavelengths = None
        
        # State variables for Absorbance math
        self.dark_spectrum = None
        self.blank_spectrum = None

    def connect(self):
        """Finds the device, resets the bus, and initializes memory."""
        print("Connecting to NanoDrop...")
        self.dev = usb.core.find(idVendor=self.VID, idProduct=self.PID)
        if self.dev is None:
            raise RuntimeError("NanoDrop not found. Is Zadig set to libusb-win32?")
        
        self.dev.set_configuration()
        self.dev.clear_halt(self.EP_OUT)
        self.dev.clear_halt(self.EP_IN_HEAVY)
        self.dev.clear_halt(self.EP_IN_COMM)

        # Wake & Init
        self._send_cmd([0x08])
        time.sleep(0.1)
        self._send_cmd([0x01])
        time.sleep(0.2)
        
        # Download machine DNA
        self._download_all_coefficients()
        self._calculate_x_axis()
        print("NanoDrop Initialized and Calibrated.")

    def close(self):
        """Safely powers down hardware and releases the USB port."""
        if self.dev:
            try:
                self.set_lamp(False)
                self.set_magnet(False)
                self.dev.reset()
                usb.util.dispose_resources(self.dev)
            except:
                pass
            print("NanoDrop safely disconnected.")

    # --- LOW LEVEL HARDWARE CONTROL ---
    def _send_cmd(self, payload):
        self.dev.write(self.EP_OUT, payload)

    def set_lamp(self, state):
        cmd = 0xFF if state else 0x00
        self._send_cmd([0x03, cmd])

    def set_magnet(self, state):
        cmd = 0xFF if state else 0x00
        self._send_cmd([0x0F, cmd])

    def set_integration_time(self, ms):
        """Sets exposure time (Valid range: 3 to 65535 ms)"""
        if ms < 3: ms = 3, print('integration too low setting 3 ms')
        if ms>65535: ms = 65535, print('integration too high setting 65535 ms')
        # Convert to 16-bit little-endian bytes
        lsb = ms & 0xFF
        msb = (ms >> 8) & 0xFF
        self._send_cmd([0x02, lsb, msb])

    # --- CALIBRATION MATH ---
    def _download_all_coefficients(self):
        """Pulls Wavelength (1-4) and Non-Linearity (6-13) coefficients."""
        print("Downloading Factory Memory Map...")
        # Flush the comm buffer first
        try:
            while True: self.dev.read(self.EP_IN_COMM, 64, timeout=50)
        except: pass

        for index in range(1, 15):
            if index == 5: continue  # Skip stray light constant for now
            self._send_cmd([0x05, index])
            time.sleep(0.05)
            try:
                data = self.dev.read(self.EP_IN_COMM, 64, timeout=500)
                text = bytearray(data[2:]).decode('ascii', errors='ignore').split('\x00')[0]
                self.coefficients[index] = float(text)
            except Exception as e:
                print(f"Warning: Failed to read coefficient index {index}")

    def _calculate_x_axis(self):
        """Builds the 2048-element wavelength array (nm)."""
        pixels = np.arange(2048)
        c0, c1 = self.coefficients.get(1, 0), self.coefficients.get(2, 0)
        c2, c3 = self.coefficients.get(3, 0), self.coefficients.get(4, 0)
        self.wavelengths = c0 + (c1 * pixels) + (c2 * (pixels**2)) + (c3 * (pixels**3))

    # --- DATA ACQUISITION ---
    def get_raw_spectrum(self):
        """Requests and decodes the interleaved 64-byte blocks."""
        # Flush stale image data
        try:
            while True: self.dev.read(self.EP_IN_HEAVY, 512, timeout=50)
        except: pass

        self._send_cmd([0x09]) # Request spectrum
        
        data_buffer = bytearray()
        for _ in range(64): 
            data_buffer.extend(self.dev.read(self.EP_IN_HEAVY, 64, timeout=1000))
            
        pixels = []
        for i in range(0, 4096, 128):
            lsb_block = data_buffer[i : i+64]
            msb_block = data_buffer[i+64 : i+128]
            for j in range(64):
                pixels.append((msb_block[j] << 8) | lsb_block[j])
                
        return np.array(pixels, dtype=float)

    # --- HIGH LEVEL SCIENTIFIC WORKFLOWS ---
    def take_blank(self, integration_ms=20):
        """Takes a dark reading, then a light reading to establish the baseline."""
        self.set_integration_time(integration_ms)
        
        # 1. Dark Spectrum (Lamp OFF)
        self.set_lamp(False)
        self.set_magnet(True) # Arm down
        time.sleep(0.2)
        print("Acquiring Dark baseline...")
        self.dark_spectrum = self.get_raw_spectrum()
        
        # 2. Blank Spectrum (Lamp ON)
        self.set_lamp(True)
        time.sleep(0.2)
        print("Acquiring Blank baseline...")
        self.blank_spectrum = self.get_raw_spectrum()
        
        self.set_lamp(False)
        self.set_magnet(False)
        print("Blanking complete.")

    def measure_absorbance(self, integration_ms=20):
        """Takes a reading and calculates the Beer-Lambert Absorbance."""
        if self.blank_spectrum is None or self.dark_spectrum is None:
            raise ValueError("You must run take_blank() before measuring!")
            
        self.set_integration_time(integration_ms)
        self.set_magnet(True)
        self.set_lamp(True)
        time.sleep(0.2)
        
        print("Measuring sample...")
        sample_spectrum = self.get_raw_spectrum()
        
        self.set_lamp(False)
        self.set_magnet(False)

        # Beer-Lambert Math: A = -log10((Sample - Dark) / (Blank - Dark))
        # We use np.clip to prevent log(0) errors caused by random camera noise
        numerator = np.clip(sample_spectrum - self.dark_spectrum, 1, None)
        denominator = np.clip(self.blank_spectrum - self.dark_spectrum, 1, None)
        
        transmittance = numerator / denominator
        absorbance = -np.log10(transmittance)
        
        return self.wavelengths, absorbance