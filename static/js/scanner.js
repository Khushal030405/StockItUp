let codeReader = null;
let activeStream = false;

const hints = new Map();
hints.set(ZXing.DecodeHintType.POSSIBLE_FORMATS, [
  ZXing.BarcodeFormat.EAN_13,
  ZXing.BarcodeFormat.EAN_8,
  ZXing.BarcodeFormat.UPC_A,
  ZXing.BarcodeFormat.UPC_E,
  ZXing.BarcodeFormat.CODE_128,
  ZXing.BarcodeFormat.CODE_39,
  ZXing.BarcodeFormat.ITF,
  ZXing.BarcodeFormat.QR_CODE
]);

function setResult(value) {
  const input = document.getElementById("scanResult");
  input.value = value;
  softBeep("success");
  lookupScanned();
}

async function startBarcodeScanner() {
  const video = document.getElementById("scannerVideo");
  const box = document.getElementById("scanInfo");

  if (!window.ZXing) {
    box.innerHTML = "<div class='flash danger'>Scanner library failed to load. Use manual entry.</div>";
    return;
  }

  try {
    stopBarcodeScanner();

    codeReader = new ZXing.BrowserMultiFormatReader(hints, 500);

    const devices = await codeReader.listVideoInputDevices();
    if (!devices || devices.length === 0) {
      box.innerHTML = "<div class='flash danger'>No camera found. Use image upload or manual entry.</div>";
      return;
    }

    const backCamera = devices.find(d =>
      /back|rear|environment/i.test(d.label)
    );

    const selectedDeviceId = backCamera ? backCamera.deviceId : devices[0].deviceId;
    activeStream = true;

    box.innerHTML = "<div class='flash success'>Camera scanner started. Point camera at barcode.</div>";

    codeReader.decodeFromVideoDevice(selectedDeviceId, video, (result, error) => {
      if (result) {
        setResult(result.getText());
        stopBarcodeScanner();
      }
    });

  } catch (err) {
    box.innerHTML = `<div class='flash danger'>
      Camera scanner could not start. Browser may require permission, localhost, or HTTPS.<br>
      Use image upload or manual entry below.
    </div>`;
  }
}

function stopBarcodeScanner() {
  try {
    if (codeReader) {
      codeReader.reset();
    }
  } catch (e) {}
  activeStream = false;
}

async function scanImageFile(event) {
  const file = event.target.files && event.target.files[0];
  const box = document.getElementById("scanInfo");

  if (!file) return;

  if (!window.ZXing) {
    box.innerHTML = "<div class='flash danger'>Scanner library failed to load. Use manual entry.</div>";
    return;
  }

  try {
    const reader = new ZXing.BrowserMultiFormatReader(hints, 500);
    const imageUrl = URL.createObjectURL(file);

    const img = document.createElement("img");
    img.src = imageUrl;
    img.style.maxWidth = "100%";
    img.style.display = "none";
    document.body.appendChild(img);

    await new Promise((resolve, reject) => {
      img.onload = resolve;
      img.onerror = reject;
    });

    const result = await reader.decodeFromImageElement(img);
    document.body.removeChild(img);
    URL.revokeObjectURL(imageUrl);

    if (result && result.getText()) {
      setResult(result.getText());
    } else {
      throw new Error("No barcode found");
    }

  } catch (err) {
    box.innerHTML = `<div class="flash danger">
      Could not read barcode from this image.<br>
      Try cropping closer to the barcode, increasing brightness, or paste/type the barcode number manually.
    </div>`;
    softBeep("warn");
  }
}

async function lookupScanned() {
  const code = document.getElementById("scanResult").value.trim();
  const box = document.getElementById("scanInfo");

  if (!code) {
    box.innerHTML = "<div class='flash danger'>No barcode entered or scanned.</div>";
    return;
  }

  const res = await fetch(`/api/product/${encodeURIComponent(code)}`);
  const data = await res.json();

  if (!data.ok) {
    box.innerHTML = `<div class="flash danger">
      Product not found for code: <b>${code}</b><br>
      Add this barcode in Inventory first, then scan again.
    </div>`;
    softBeep("warn");
    return;
  }

  const p = data.product;
  box.innerHTML = `<div class="panel scan-card">
    <h3>${p.name}</h3>
    <p><b>Barcode / QR:</b> ${p.barcode}</p>
    <p><b>Category:</b> ${p.category}</p>
    <p><b>Brand:</b> ${p.brand || "-"}</p>
    <p><b>Price:</b> ₹${Number(p.selling_price).toFixed(2)}</p>
    <p><b>Stock:</b> ${p.quantity}</p>
    <a class="btn primary" href="/billing">Go to Billing</a>
  </div>`;
}
