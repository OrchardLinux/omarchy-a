<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 512 512">
  <title>Firefox</title>
  <desc>Firefox's logo in the theme's colors: the fox in the main color curled around a pale globe, its head and ear up at the right and its tail sweeping over the top, with a hard shadow.</desc>
  <defs>
    <linearGradient id="main" x1="0" y1="0" x2="1" y2="1">
      <stop stop-color="{{ icon_main }}"/>
      <stop offset="1" stop-color="{{ icon_main_end }}"/>
    </linearGradient>
  </defs>
  <g transform="translate(256 256) scale(1.2) translate(-256 -256)">
    <!-- Its silhouette, as one hard shadow, as Hype's slides. -->
    <g transform="translate(0 9)" fill="{{ icon_shadow }}">
      <circle cx="236" cy="246" r="126"/>
      <path d="M104 185A168 168 0 1 0 396 164Q424 118 380 62Q378 100 346 116Q330 132 332 165A126 126 0 1 1 118 203Z"/>
      <path d="M104 185A168 168 0 0 1 212 94Q256 80 306 92Q248 98 206 120Q140 146 104 226Z"/>
    </g>
    <!-- The globe, pale, a band of the main color across it. -->
    <circle cx="236" cy="246" r="126" fill="{{ icon_paper }}"/>
    <path d="M114 222Q236 186 360 226Q364 262 352 292Q238 256 118 290Q108 256 114 222Z" fill="{{ icon_main }}" fill-opacity=".22"/>
    <!-- The fox: its body around the right and bottom of the globe, the head
         and ear at the top right. -->
    <path d="M104 185A168 168 0 1 0 396 164Q424 118 380 62Q378 100 346 116Q330 132 332 165A126 126 0 1 1 118 203Z" fill="url(#main)"/>
    <!-- Its tail, over the top of the globe to a point before the head. -->
    <path d="M104 185A168 168 0 0 1 212 94Q256 80 306 92Q248 98 206 120Q140 146 104 226Z" fill="url(#main)"/>
  </g>
</svg>
