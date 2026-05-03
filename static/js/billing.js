let cart = [];
let billingCodeReader = null;

const billingHints = new Map();
if (window.ZXing) {
  billingHints.set(ZXing.DecodeHintType.POSSIBLE_FORMATS, [
    ZXing.BarcodeFormat.EAN_13,
    ZXing.BarcodeFormat.EAN_8,
    ZXing.BarcodeFormat.UPC_A,
    ZXing.BarcodeFormat.UPC_E,
    ZXing.BarcodeFormat.CODE_128,
    ZXing.BarcodeFormat.CODE_39,
    ZXing.BarcodeFormat.ITF,
    ZXing.BarcodeFormat.QR_CODE
  ]);
}

async function fetchProduct(barcode){
  const res = await fetch(`/api/product/${encodeURIComponent(barcode)}`);
  return await res.json();
}

async function addByBarcode(){
  const input = document.getElementById("barcodeInput");
  const code = input.value.trim();

  if(!code){
    alert("Enter barcode");
    return false;
  }

  const data = await fetchProduct(code);
  if(!data.ok){
    alert(data.message || "Product not found");
    return false;
  }

  addProduct(data.product);
  input.value = "";
  return true;
}

async function addSelected(){
  const select = document.getElementById("productSelect");
  const code = select.value;

  if(!code){
    return false;
  }

  document.getElementById("barcodeInput").value = code;
  const added = await addByBarcode();

  // Reset dropdown so the same product can be selected again later.
  select.value = "";

  return added;
}

function addProduct(p){
  const existing = cart.find(x => x.barcode === p.barcode);

  if(existing){
    existing.qty += 1;
  } else {
    cart.push({
      barcode: String(p.barcode),
      name: p.name,
      price: Number(p.selling_price),
      qty: 1
    });
  }

  renderCart();
  softBeep("success");
}

function changeQty(index, qty){
  const newQty = Math.max(1, Number(qty || 1));
  cart[index].qty = newQty;
  renderCart();
}

function removeItem(index){
  cart.splice(index,1);
  renderCart();
}

function renderCart(){
  const table = document.getElementById("cartTable");
  table.innerHTML = "<tr><th>Product</th><th>Barcode</th><th>Price</th><th>Qty</th><th>Subtotal</th><th></th></tr>";

  let total = 0;

  cart.forEach((item, i)=>{
    const sub = Number(item.price) * Number(item.qty);
    total += sub;

    table.innerHTML += `<tr>
      <td>${item.name}</td>
      <td>${item.barcode}</td>
      <td>₹${Number(item.price).toFixed(2)}</td>
      <td><input style="width:80px" type="number" value="${item.qty}" min="1" onchange="changeQty(${i}, this.value)"></td>
      <td>₹${sub.toFixed(2)}</td>
      <td><button type="button" class="mini danger-btn" onclick="removeItem(${i})">Remove</button></td>
    </tr>`;
  });

  document.getElementById("cartTotal").textContent = total.toFixed(2);
}

function submitBill(e){
  e.preventDefault();

  if(cart.length === 0){
    alert("Cart is empty. Select a product or scan a barcode first.");
    return false;
  }

  const cleanCart = cart
    .filter(x => x.barcode && Number(x.qty) > 0)
    .map(x => ({
      barcode: String(x.barcode),
      qty: Number(x.qty)
    }));

  if(cleanCart.length === 0){
    alert("Cart data is invalid. Please add the product again.");
    return false;
  }

  document.getElementById("itemsJson").value = JSON.stringify(cleanCart);
  document.getElementById("billForm").submit();
}

/* Billing scanner */
function openBillingScanner(){
  document.getElementById("billingScannerModal").style.display = "flex";
  document.getElementById("billingScannerStatus").textContent = "";
  startBillingScanner();
}

function closeBillingScanner(){
  stopBillingScanner();
  document.getElementById("billingScannerModal").style.display = "none";
}

async function handleBillingScan(value){
  document.getElementById("barcodeInput").value = value;
  document.getElementById("billingScannerStatus").innerHTML = "Detected: <b>" + value + "</b>. Adding item...";
  await addByBarcode();
}

async function startBillingScanner(){
  const video = document.getElementById("billingScannerVideo");
  const status = document.getElementById("billingScannerStatus");

  if(!window.ZXing){
    status.textContent = "Scanner library could not load. Please type barcode manually.";
    return;
  }

  try{
    stopBillingScanner();

    billingCodeReader = new ZXing.BrowserMultiFormatReader(billingHints, 500);
    const devices = await billingCodeReader.listVideoInputDevices();

    if(!devices || devices.length === 0){
      status.textContent = "No camera found. Use image upload or manual entry.";
      return;
    }

    const backCamera = devices.find(d => /back|rear|environment/i.test(d.label));
    const selectedDeviceId = backCamera ? backCamera.deviceId : devices[0].deviceId;

    status.textContent = "Camera started. Scan item barcode.";

    billingCodeReader.decodeFromVideoDevice(selectedDeviceId, video, async (result, error) => {
      if(result){
        await handleBillingScan(result.getText());
        stopBillingScanner();
      }
    });
  }catch(err){
    status.textContent = "Camera could not start. Allow camera permission or use image/manual entry.";
  }
}

function stopBillingScanner(){
  try{
    if(billingCodeReader){
      billingCodeReader.reset();
    }
  }catch(e){}
}

async function scanBillingImage(event){
  const file = event.target.files && event.target.files[0];
  const status = document.getElementById("billingScannerStatus");
  if(!file) return;

  if(!window.ZXing){
    status.textContent = "Scanner library could not load. Please type barcode manually.";
    return;
  }

  try{
    const reader = new ZXing.BrowserMultiFormatReader(billingHints, 500);
    const imageUrl = URL.createObjectURL(file);

    const img = document.createElement("img");
    img.src = imageUrl;
    img.style.display = "none";
    document.body.appendChild(img);

    await new Promise((resolve, reject) => {
      img.onload = resolve;
      img.onerror = reject;
    });

    const result = await reader.decodeFromImageElement(img);

    document.body.removeChild(img);
    URL.revokeObjectURL(imageUrl);

    if(result && result.getText()){
      await handleBillingScan(result.getText());
    }else{
      throw new Error("No barcode found");
    }
  }catch(err){
    status.textContent = "Could not read this image. Try a clearer/cropped barcode image.";
    softBeep("warn");
  }
}

document.addEventListener("DOMContentLoaded", renderCart);
