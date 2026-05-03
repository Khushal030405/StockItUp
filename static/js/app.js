function softBeep(type="success"){
  try{
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.frequency.value = type === "warn" ? 220 : 520;
    gain.gain.value = 0.05;
    osc.start();
    setTimeout(()=>{osc.stop(); ctx.close();}, 120);
  }catch(e){}
}

document.addEventListener("DOMContentLoaded", () => {
  if (window.chartData && document.getElementById("salesChart")) {
    new Chart(document.getElementById("salesChart"), {
      type: "line",
      data: {
        labels: window.chartData.dailyLabels,
        datasets: [{ label: "Revenue", data: window.chartData.dailyValues, tension: .35 }]
      },
      options: { responsive: true, plugins: { legend: { display: false } } }
    });
  }

  if (window.chartData && document.getElementById("topChart")) {
    new Chart(document.getElementById("topChart"), {
      type: "bar",
      data: {
        labels: window.chartData.topLabels,
        datasets: [{ label: "Sold Qty", data: window.chartData.topValues }]
      },
      options: { responsive: true, plugins: { legend: { display: false } } }
    });
  }
});
