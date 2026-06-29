import matplotlib.pyplot as plt
from nanodrop import NanoDrop1000

def main():
    nd = NanoDrop1000()
    
    try:
        nd.connect()
        
        print("\n--- Calibration Data ---")
        print(f"C0 (Intercept): {nd.coefficients.get(1)}")
        print(f"C1 (Linear): {nd.coefficients.get(2)}")
        
        input("\n1. Place your BLANK (e.g., pure water) on the pedestal, close the arm, and press Enter...")
        nd.take_blank(integration_ms=20)
        
        input("\n2. Wipe the pedestal, place your SAMPLE (e.g., DNA/Protein), close the arm, and press Enter...")
        wavelengths, absorbance = nd.measure_absorbance(integration_ms=20)
        
        print("\nPlotting Absorbance Data...")
        plt.figure(figsize=(10, 5))
        # Plot only the active sensor area (roughly 220nm to 750nm)
        plt.plot(wavelengths[26:2047], absorbance[26:2047], color='blue')
        plt.title("NanoDrop 1000 - Real Absorbance Measurement")
        plt.xlabel("Wavelength (nm)")
        plt.ylabel("Absorbance (A)")
        plt.grid(True)
        plt.xlim(220, 750)
        # Typical DNA peak is at 260nm, Protein at 280nm
        plt.axvline(260, color='red', linestyle='--', label='260nm (DNA)')
        plt.axvline(280, color='green', linestyle='--', label='280nm (Protein)')
        plt.legend()
        plt.show()

    except Exception as e:
        print(f"\n[ERROR]: {e}")
    finally:
        nd.close()

if __name__ == "__main__":
    main()