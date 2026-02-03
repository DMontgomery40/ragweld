// Legacy layout_fix.js module (archived).
//
// This module used to mutate the DOM at runtime to ensure `.sidepanel` was a direct
// child of `.layout` and ordered correctly relative to `.content` and `.resize-handle`.
//
// The React `App.tsx` now renders a stable `.layout` structure (grid + handle + content + sidepanel),
// so this runtime DOM surgery is no longer needed.
(function () {
  'use strict';

  function fixSidepanelPlacement() {
    try {
      var layout = document.querySelector('.layout');
      if (!layout) return;
      var content = layout.querySelector(':scope > .content') || document.querySelector('.content');
      var sidepanel = document.querySelector('.sidepanel');
      if (!content || !sidepanel) return;

      // If sidepanel is not a direct child of layout, move it after content
      if (sidepanel.parentElement !== layout) {
        layout.appendChild(sidepanel);
      }
      // Ensure correct ordering: content first, sidepanel second
      if (content.nextElementSibling !== sidepanel) {
        layout.insertBefore(sidepanel, content.nextElementSibling);
      }
      // Ensure resize handle (if any) stays before content
      var handle = layout.querySelector(':scope > .resize-handle');
      if (handle && handle.nextElementSibling !== content) {
        layout.insertBefore(content, handle.nextElementSibling);
      }
    } catch (e) {
      /* best effort */
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', fixSidepanelPlacement);
  } else {
    fixSidepanelPlacement();
  }
})();

