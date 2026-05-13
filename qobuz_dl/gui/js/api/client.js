(function () {
  "use strict";

  const root = (window.QobuzGui = window.QobuzGui || {});

  async function request(path, options) {
    const res = await fetch(path, options);
    const data = await res.json();
    return { res, data };
  }

  function getJson(path) {
    return request(path);
  }

  function postJson(path, body) {
    return request(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
  }

  root.api = {
    getJson,
    postJson,
    request,
  };
})();
