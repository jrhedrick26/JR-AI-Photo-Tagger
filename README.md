# JR AI Photo Tagger 📸🤖

An open-source, professional-grade desktop workspace that leverages Google's Gemini 2.5 Flash AI to automatically generate highly accurate, contextual, and editorial Titles, Captions, and Keywords for photography collections.

It reads camera EXIF/GPS context and safely writes metadata directly inside your JPEGs, TIFFs, DNGs, and proprietary RAW formats (Sony ARW, Canon CR2, Nikon NEF) using industry-standard ExifTool.

---

## 📋 Quick Start (No Terminal Required)

### macOS
1. Download and install [ExifTool](https://exiftool.org/) (macOS Package .pkg)
2. Download **JR_AI_Photo_Tagger.dmg** from [Releases](https://github.com/jrhedrick26/JR-AI-Photo-Tagger/releases)
3. Drag the app to your Applications folder
4. Get a free Gemini API key at [ai.google.dev](https://ai.google.dev/)
5. Launch the app and paste your API key!

### Windows
1. Create a folder: `C:\Users\YourName\Documents\JR AI Photo Tagger`
2. Download **JR_AI_Photo_Tagger.exe** from [Releases](https://github.com/jrhedrick26/JR-AI-Photo-Tagger/releases)
3. Download ExifTool from [exiftool.org](https://exiftool.org/), extract, rename `exiftool(-k).exe` → `exiftool.exe`
4. Place both files in your app folder
5. Get a free Gemini API key at [ai.google.dev](https://ai.google.dev/)
6. Run the .exe and paste your API key!

---

## 🍏 macOS Installation (Detailed)

### 1. Install ExifTool Engine

**Option A: GUI Installer (Recommended - No Terminal)**
* Go to [exiftool.org](https://exiftool.org/)
* Download the **macOS Package (.pkg)** installer
* Double-click the `.pkg` file and follow the installer prompts
* Done! ExifTool is now installed

**Option B: Homebrew (For Advanced Users)**
If you have Homebrew installed, you can also run:
```bash
brew install exiftool
```

### 2. Download the App Installer
* Go to the **[Releases](https://github.com/jrhedrick26/JR-AI-Photo-Tagger/releases)** page
* Download the **`JR_AI_Photo_Tagger.dmg`** file
* Double-click the `.dmg` to open the installer window
* Drag **JR AI Photo Tagger.app** into your Mac's **Applications** folder

### 3. First-Time Launch (Security Bypass)
Because this app is distributed outside the App Store, macOS shows a security warning on first launch:

1. Double-click the app in **Applications**. When warned it "cannot be verified," click **Done**
2. Open **System Settings** → **Privacy & Security** (left sidebar)
3. Scroll down to **Security** section
4. Find "JR AI Photo Tagger.app was blocked..." and click **Open Anyway**
5. Enter your Mac password or use Touch ID to authorize
6. The app will launch! You only do this once.

---

## 🪟 Windows Installation (Detailed)

### 1. Create Your App Folder
Create a new folder on your computer:
- Example: `C:\Users\YourName\Documents\JR AI Photo Tagger`
- Or use Desktop: `C:\Users\YourName\Desktop\JR AI Photo Tagger`

### 2. Download the App Executable
* Go to the **[Releases](https://github.com/jrhedrick26/JR-AI-Photo-Tagger/releases)** page
* Download the **`JR_AI_Photo_Tagger.exe`** file
* Move it into your app folder

### 3. Download & Configure ExifTool
Windows requires ExifTool to be in the same folder as the app:

* Go to [exiftool.org](https://exiftool.org/)
* Download the **Windows Executable** zip file (e.g., `exiftool-12.50.zip`)
* Unzip it
* Find `exiftool(-k).exe` and cut/copy it
* Paste it into your app folder
* **CRITICAL:** Rename `exiftool(-k).exe` → **`exiftool.exe`** (remove the `-k` part)

Your folder should look like this:
```
📂 JR AI Photo Tagger
 ├── 📄 JR_AI_Photo_Tagger.exe
 └── 📄 exiftool.exe
```

### 4. Launch the App
Double-click `JR_AI_Photo_Tagger.exe` to start!

---

## 🔑 Getting Your Gemini API Key

1. **Visit** [ai.google.dev](https://ai.google.dev/)
2. **Sign in** with your Google account (or create one free)
3. **Click** "Get API Key" → "Create API Key in new project"
4. **Copy** your API key
5. **Paste** it into the JR AI Photo Tagger app
6. **Done!** New users get $300/month in free API credits

---

## 📖 How to Use

### Setup
1. Enter your **Gemini API Key** (one-time setup, securely stored)
2. Enter your **Creator Name** (appears as photo copyright holder)
3. Enter your **Copyright Notice** (e.g., "© 2026 Your Name")

### Processing Photos
1. Click **+ Add Files** or **+ Add Folder** to load photos
2. Select an **AI Style** (Standard, Real Estate, Portrait, Landscape, Drone, Street, Travel)
3. Optionally add **Batch Notes** (e.g., "Client: ABC Corp, Event: Annual Gala")
4. Click **Generate AI** to analyze your photos
5. Review and edit metadata in the table
6. Click **Commit Changes** to write metadata to your files

### After Processing
- **Lightroom Users:** Open Lightroom Classic, select your photos, go to **Metadata → Read Metadata from File** to import the newly written data
- **Logs:** Check `~/Documents/JR AI Photo Tagger/logs/` for audit trails of each batch

---

## 💻 Developer Setup

### Requirements
- **Python 3.8+** (download from [python.org](https://www.python.org/downloads/))
- **pip** (included with Python)
- **ExifTool** (see installation guide above)

### Installation
```bash
# Clone the repository
git clone https://github.com/jrhedrick26/JR-AI-Photo-Tagger.git
cd JR-AI-Photo-Tagger

# Create a virtual environment (recommended)
python -m venv venv

# Activate virtual environment
# macOS/Linux:
source venv/bin/activate
# Windows:
venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### Running from Source
```bash
python app.py
```

### Building Standalone Executables
We use PyInstaller to create distributable binaries:

```bash
# Install build dependencies
pip install pyinstaller

# macOS (creates .app and .dmg)
pyinstaller --onefile --windowed --name "JR AI Photo Tagger" app.py

# Windows (creates .exe)
pyinstaller --onefile --windowed --name "JR_AI_Photo_Tagger" app.py
```

The built app will be in the `dist/` folder.

---

## 🤝 Contributing

We welcome contributions! Here's how:

1. Fork the repository
2. Create a feature branch: `git checkout -b fix/your-feature`
3. Make your changes
4. Test thoroughly
5. Push to your fork and open a Pull Request

---

## 📝 License

This project is licensed under the MIT License. See [LICENSE](LICENSE) file for details.

---

## 🐛 Troubleshooting

### "ExifTool is not installed"
**macOS:** Make sure you downloaded and ran the ExifTool `.pkg` installer from [exiftool.org](https://exiftool.org/), or install via Homebrew with `brew install exiftool`  
**Windows:** Make sure `exiftool.exe` is in the same folder as the app, and the filename is exactly correct (no `-k` suffix)

### "API Key rejected" or "Configuration Error"
- Make sure your API key is correct (no extra spaces)
- Visit [ai.google.dev](https://ai.google.dev/) to verify your key is valid
- Ensure you have free credits remaining (new users get $300/month)

### "API Rate Limited"
The app automatically throttles requests when hitting rate limits. Your batch will complete, just slower. Consider processing smaller batches (50-100 images at a time).

### "Permission denied on files"
**macOS:** Grant folder access in System Settings → Privacy & Security → Files and Folders  
**Windows:** Make sure your user account has read/write permissions for the photo folder

### Large Folder Scan is Slow
The app scans recursively through all subfolders. For folders with thousands of images, this may take 30+ seconds. A progress dialog will appear during the scan.

---

## 📞 Support

- **Questions?** Open an [Issue](https://github.com/jrhedrick26/JR-AI-Photo-Tagger/issues)
- **Feature request?** Open a [Discussion](https://github.com/jrhedrick26/JR-AI-Photo-Tagger/discussions)
- **Found a bug?** Report it in [Issues](https://github.com/jrhedrick26/JR-AI-Photo-Tagger/issues)

---

**Made with ❤️ for photographers**
