# JR AI Photo Tagger 📸🤖 (macOS Workspace)

An open-source, professional-grade desktop workspace that leverages Google's Gemini 2.5 Flash AI to automatically generate highly accurate, contextual, and editorial Titles, Captions, and Keywords for your photography batches. 

It reads camera EXIF/GPS context and safely writes metadata directly inside your JPEGs, TIFFs, DNGs, and proprietary RAW formats (Sony ARW, Canon CR2, Nikon NEF) using industry-standard ExifTool.

---

## 🚀 How to Install & Run (No Terminal Required)

**1. Install the ExifTool Engine**
The app relies on ExifTool to bake metadata safely into your photos without altering image pixels.
* Go to the official website: [exiftool.org](https://exiftool.org/).
* Download and run the **macOS Package (.pkg)** installer to set up the background engine.

**2. Download the App Bundle**
* Go to the **Releases** section on the right side of this GitHub repository page.
* Download the `JR.AI.Photo.Tagger.zip` folder.
* Unzip the folder and drag the **JR AI Photo Tagger.app** icon right into your Mac's Applications folder!

**3. Fire Up the App**
* Double-click the icon to open it. 
* *Note: Because this is open-source software outside the official Apple App Store, the first time you run it, you must **Right-Click (Control-Click)** the app icon and choose **Open**, then select **Open anyway** on the security card. This tells macOS to permanently trust the app going forward.*
* Generate a free Gemini API Key via [Google AI Studio](https://aistudio.google.com/app/apikey) and paste it into the application to begin processing batches!

---

## 💻 For Developers (Natively Run Source Code)

If you are a developer looking to adapt the script or contribute directly to prompt iterations:

```bash
# Clone the repository
git clone [https://github.com/YOUR_GITHUB_USERNAME/JR-AI-Photo-Tagger.git](https://github.com/YOUR_GITHUB_USERNAME/JR-AI-Photo-Tagger.git)
cd JR-AI-Photo-Tagger

# Setup cross-platform packages
python3 -m pip install -r requirements.txt

# Launch raw application
python3 app.py
