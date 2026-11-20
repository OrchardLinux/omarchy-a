<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 512 512">
  <title>Settings</title>
  <desc>A gear in the theme's colors: eight square teeth around a body in the main color, a pale ring set into it and a hole through the middle, with a hard shadow.</desc>
  <defs>
    <linearGradient id="main" x1="0" y1="0" x2="1" y2="1">
      <stop stop-color="{{ icon_main }}"/>
      <stop offset="1" stop-color="{{ icon_main_end }}"/>
    </linearGradient>
  </defs>
  <!-- Its silhouette, as one hard shadow, as Hype's slides. -->
  <path d="M228.0 114.9 L231.2 75.8 L280.8 75.8 L284.0 114.9 L331.8 134.7 L361.7 109.3 L396.7 144.3 L371.3 174.2 L391.1 222.0 L430.2 225.2 L430.2 274.8 L391.1 278.0 L371.3 325.8 L396.7 355.7 L361.7 390.7 L331.8 365.3 L284.0 385.1 L280.8 424.2 L231.2 424.2 L228.0 385.1 L180.2 365.3 L150.3 390.7 L115.3 355.7 L140.7 325.8 L120.9 278.0 L81.8 274.8 L81.8 225.2 L120.9 222.0 L140.7 174.2 L115.3 144.3 L150.3 109.3 L180.2 134.7Z" fill="{{ icon_shadow }}" transform="translate(0 10)"/>
  <!-- The gear, the hole cut through it. -->
  <path d="M228.0 114.9 L231.2 75.8 L280.8 75.8 L284.0 114.9 L331.8 134.7 L361.7 109.3 L396.7 144.3 L371.3 174.2 L391.1 222.0 L430.2 225.2 L430.2 274.8 L391.1 278.0 L371.3 325.8 L396.7 355.7 L361.7 390.7 L331.8 365.3 L284.0 385.1 L280.8 424.2 L231.2 424.2 L228.0 385.1 L180.2 365.3 L150.3 390.7 L115.3 355.7 L140.7 325.8 L120.9 278.0 L81.8 274.8 L81.8 225.2 L120.9 222.0 L140.7 174.2 L115.3 144.3 L150.3 109.3 L180.2 134.7ZM198.0 250.0a58 58 0 1 0 116 0a58 58 0 1 0 -116 0Z" fill="url(#main)" fill-rule="evenodd" stroke="{{ icon_edge }}" stroke-width="3"/>
  <!-- A pale ring set into the face. -->
  <path d="M156.0 250.0a100 100 0 1 0 200 0a100 100 0 1 0 -200 0ZM184.0 250.0a72 72 0 1 0 144 0a72 72 0 1 0 -144 0Z" fill="{{ icon_paper }}" fill-rule="evenodd"/>
</svg>
