(function () {
  "use strict";
  const ui = (window.QobuzGui.ui = window.QobuzGui.ui || {});
  ui.donationPopover = ui.donationPopover || {};

  ui.donationPopover.init = function initDonationPopover() {
    const btn = document.getElementById("monero-btn");
    const pop = document.getElementById("donation-popover");
    const copyBtn = document.getElementById("copy-address-btn");
    const addrEl = document.getElementById("monero-address");
    const copyText = document.getElementById("copy-text");

    if (!btn || !pop) return;

    function togglePopover(e) {
      if (e) e.stopPropagation();
      const isHidden = pop.classList.contains("hidden");

      if (isHidden) {
        pop.classList.remove("hidden");
        const btnRect = btn.getBoundingClientRect();
        pop.style.bottom = window.innerHeight - btnRect.top + 10 + "px";
        let left = btnRect.left + btnRect.width / 2 - pop.offsetWidth / 2;
        pop.style.left =
          Math.max(10, Math.min(left, window.innerWidth - pop.offsetWidth - 10)) +
          "px";
        btn.classList.add("active");
      } else {
        hidePopover();
      }
    }

    function hidePopover() {
      pop.classList.add("hidden");
      btn.classList.remove("active");
    }

    btn.addEventListener("click", togglePopover);

    document.addEventListener("click", (e) => {
      if (
        !pop.classList.contains("hidden") &&
        !pop.contains(e.target) &&
        !btn.contains(e.target)
      ) {
        hidePopover();
      }
    });

    if (copyBtn && addrEl) {
      copyBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        const addr = addrEl.textContent.trim();
        navigator.clipboard.writeText(addr).then(() => {
          const original = copyText.textContent;
          copyText.textContent = "Copied!";
          copyBtn.style.background = "var(--success)";
          copyBtn.style.color = "white";
          setTimeout(() => {
            copyText.textContent = original;
            copyBtn.style.background = "";
            copyBtn.style.color = "";
          }, 2000);
        });
      });
    }
  };
})();
