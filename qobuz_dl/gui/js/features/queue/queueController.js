(function () {
  "use strict";
  const g = window.QobuzGui;
  const features = (g.features = g.features || {});

  /** Real impl; wired once via `install` after download queue exists in app.js. */
  let _impl = null;

  function install(impl) {
    _impl = impl;
  }

  function addUrl(url) {
    return _impl && _impl.addUrl ? _impl.addUrl(url) : undefined;
  }

  function removeUrl(url) {
    return _impl && _impl.removeUrl ? _impl.removeUrl(url) : undefined;
  }

  function hasUrl(url) {
    return !!(url && _impl && typeof _impl.hasUrl === "function" && _impl.hasUrl(url));
  }

  function getQueuedUrlSet() {
    return _impl && _impl.getQueuedUrlSet ? _impl.getQueuedUrlSet() : new Set();
  }

  function handleDrop(e) {
    if (_impl && typeof _impl.handleDrop === "function") return _impl.handleDrop(e);
  }

  function handleDropText(e) {
    if (_impl && typeof _impl.handleDropText === "function") {
      return _impl.handleDropText(e);
    }
  }

  function updateBadge() {
    if (_impl && typeof _impl.updateBadge === "function") {
      return _impl.updateBadge();
    }
  }

  features.queue = {
    install,
    addUrl,
    removeUrl,
    hasUrl,
    getQueuedUrlSet,
    handleDrop,
    handleDropText,
    updateBadge,
  };
})();
