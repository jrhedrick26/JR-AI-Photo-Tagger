# JR AI Photo Tagger 📸🤖 (macOS Workspace)

An open-source, professional-grade desktop workspace that leverages Google's Gemini 2.5 Flash AI to automatically generate highly accurate, contextual, and editorial Titles, Captions, and Keywords for your photography batches. 

It reads camera EXIF/GPS context and safely writes metadata directly inside your JPEGs, TIFFs, DNGs, and proprietary RAW formats (Sony ARW, Canon CR2, Nikon NEF) using industry-standard ExifTool.

---

## 🚀 How to Install & Run (No Terminal Required)

**1. Install the ExifTool Engine**
The app relies on ExifTool to bake metadata safely into your photos without altering image pixels.
* Go to the official website: [exiftool.org](https://exiftool.org/).
* Download and run the **macOS Package (.pkg)** installer to set up the background engine.

**2. Download the App Installer**
* Go to the **Releases** section on the right-hand sidebar of this GitHub repository page.
* Download the **`JR_AI_Photo_Tagger.dmg`** file.
* Double-click the downloaded `.dmg` file to open the installer window, then drag the **JR AI Photo Tagger.app** icon and drop it directly into your Mac's **Applications** folder.

**3. Fire Up the App (First-Time Security Bypass)**
Because this is open-source software distributed outside the official Apple App Store, macOS will show a security block when you first try to open it. To authorize it, follow these quick steps:
1. Double-click the app icon inside your **Applications** folder. When the warning box pops up stating it cannot be verified, click **Done**.
2. Click the **Apple icon ()** in the top-left corner of your Mac screen and choose **System Settings...**
3. Navigate to **Privacy & Security** on the left sidebar, then scroll down on the right side until you see the **Security** heading.
4. Look for the message stating *"JR AI Photo Tagger.app was blocked from use..."* and click the **Open Anyway** button next to it.
5. Provide your Mac user password or Touch ID, then click **Open** on the final confirmation card.

*Note: You only have to do this once! Your Mac will permanently remember this exception, and you can double-click the app icon to run it normally going forward.*

---

## 🔑 Activating the AI Core

1. Generate a free Gemini API Key via [Google AI Studio](https://aistudio.google.com/app/apikey).
2. Open the app, paste your key into the top-row input field, and you are ready to begin processing your photo batches!

---

## 💻 For Developers (Natively Run Source Code)

If you are a developer looking to adapt the script natively or contribute directly to prompt iterations:

```bash
# Clone the repository
git clone [https://github.com/YOUR_GITHUB_USERNAME/JR-AI-Photo-Tagger.git](https://github.com/YOUR_GITHUB_USERNAME/JR-AI-Photo-Tagger.git)
cd JR-AI-Photo-Tagger

# Setup cross-platform packages
python3 -m pip install -r requirements.txt

# Launch raw application
python3 app.py
