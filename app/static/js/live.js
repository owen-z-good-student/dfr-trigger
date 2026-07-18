class LiveController {
  attach() {
    const list = document.getElementById("live-list");
    if (!list) return;
    this._load();
  }

  async _load() {
    const list = document.getElementById("live-list");
    if (!list) return;
    try {
      const result = await apiClient.get("/api/live");
      if (!result.shares || !result.shares.length) {
        list.innerHTML = '<p class="log-record-meta" data-i18n="live.no_stream">No active livestream</p>';
        I18N.apply();
        return;
      }
      list.innerHTML = "";
      result.shares.forEach(share => {
        const card = document.createElement("div");
        card.className = "live-card";
        card.innerHTML =
          '<div class="live-card-header">' + (share.device_sn || "—") + '</div>' +
          '<iframe src="' + share.share_url + '" allowfullscreen class="live-iframe"></iframe>';
        list.appendChild(card);
      });
    } catch (_) {
      list.innerHTML = '<p class="log-record-meta" data-i18n="live.no_stream">No active livestream</p>';
      I18N.apply();
    }
  }
}