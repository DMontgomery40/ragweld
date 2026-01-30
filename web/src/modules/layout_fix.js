// Layout guard: ensures the sidepanel is a sibling of .content under .layout
// Some merges left the sidepanel nested inside .content in certain snapshots.
// This script corrects the DOM at runtime without changing styles.
(function(){
  'use strict';
  /**
   * ---agentspec
   * what: |
   *   Fixes sidepanel DOM placement by moving it to direct child of layout after content. Queries .layout, .content, .sidepanel; relocates sidepanel if not already positioned correctly.
   *
   * why: |
   *   Ensures consistent DOM hierarchy for CSS layout rules (flexbox/grid) to work predictably.
   *
   * guardrails:
   *   - DO NOT assume .layout exists; returns silently if missing
   *   - NOTE: Mutates DOM; call only after page fully loaded
   *   - DO NOT use on dynamically injected content without re-running
   * ---/agentspec
   */
  function fixSidepanelPlacement(){
    try{
      var layout = document.querySelector('.layout');
      if (!layout) return;
      var content = layout.querySelector(':scope > .content') || document.querySelector('.content');
      var sidepanel = document.querySelector('.sidepanel');
      if (!content || !sidepanel) return;

      // If sidepanel is not a direct child of layout, move it after content
      if (sidepanel.parentElement !== layout){
        layout.appendChild(sidepanel);
      }
      // Ensure correct ordering: content first, sidepanel second
      if (content.nextElementSibling !== sidepanel){
        layout.insertBefore(sidepanel, content.nextElementSibling);
      }
      // Ensure resize handle (if any) stays before content
      var handle = layout.querySelector(':scope > .resize-handle');
      if (handle && handle.nextElementSibling !== content){
        layout.insertBefore(content, handle.nextElementSibling);
      }
    }catch(e){ /* best effort */ }
  }

  if (document.readyState === 'loading'){
    document.addEventListener('DOMContentLoaded', fixSidepanelPlacement);
  } else {
    fixSidepanelPlacement();
  }
})();

