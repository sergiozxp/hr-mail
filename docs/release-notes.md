**Versión de prueba 0.2.0.** Ahora funciona con casi cualquier radio moderna, eligiendo todo con el mouse.

### Novedades
- **Elija su radio de una lista**: ICOM IC-7100, IC-7300, IC-705, IC-7610, IC-9700, IC-7600, IC-7410, IC-7200; Yaesu FT-710, FT-991/991A, FT-891, FTDX10, FTDX101D/MP, FTDX3000; Kenwood TS-590S/SG, TS-890S, TS-480; Elecraft K3, KX3, KX2, K4; Xiegu G90, X6100.
- **¿Su radio no está?** Elija *Otro modelo (lista completa de hamlib)* y búsquela por marca o modelo.
- **Cuatro formas de transmitir (PTT)**: por el cable USB de la radio (CAT, recomendado), por RTS/DTR (Digirig, AIOC, cables caseros), con interfaz CM108, o con VOX.
- **Buscar radio**: encuentra solo el puerto COM y la velocidad. No transmite.
- **Probar PTT**: la radio transmite 1 segundo para comprobar que todo está bien conectado.
- Sus ajustes de la versión 0.1.0 se conservan.

### Ejemplo: Yaesu FT-710 con un solo cable USB
1. Radio: **Yaesu FT-710**. Conexión PTT: **CAT por el cable USB de la radio**.
2. Pulse **Buscar radio** (encuentra el puerto "Enhanced").
3. Pulse **Detectar audio** y luego **Probar PTT**.

### Cómo instalar
1. Descargue el archivo **hr-mail-…-windows.zip** (abajo, en *Assets*).
2. Clic derecho sobre el ZIP → **Extraer todo**.
3. Abra la carpeta **hr-mail** y haga doble clic en **hr-mail.exe**.

No necesita instalador ni permisos de administrador.

### Avisos de Windows
- **"Windows protegió su PC"**: pulse *Más información* → *Ejecutar de todas formas* (el programa no está firmado).
- **Firewall para mercury.exe**: puede pulsar *Cancelar*; hr-mail no necesita acceso a la red.

### Importante
Solo el IC-7100 está probado en el aire. Las demás radios usan la configuración de fábrica conocida; si alguna no funciona, avise con el modelo y lo que muestra la ventana.

### Incluye
Mercury 1.9.19 (módem HF libre, con hamlib 4.6.5) y Pat 1.0.0 (correo P2P), sin modificar. Software libre bajo GPL-3.0.
