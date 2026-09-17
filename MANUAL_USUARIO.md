# Manual de usuario de bibgraph

## Índice

- [Parte I. Manual completo](#parte-i-manual-completo)
  - [1. Portada](#1-portada)
  - [2. Resumen de cinco minutos](#2-resumen-de-cinco-minutos)
  - [3. Conceptos básicos](#3-conceptos-básicos)
  - [4. Requisitos previos](#4-requisitos-previos)
  - [5. Entrar en la carpeta del proyecto](#5-entrar-en-la-carpeta-del-proyecto)
  - [6. Primera comprobación](#6-primera-comprobación)
  - [7. Preparar la bibliografía](#7-preparar-la-bibliografía)
  - [8. Importar el catálogo](#8-importar-el-catálogo)
  - [9. Configurar las dependencias](#9-configurar-las-dependencias)
  - [10. Validar la configuración](#10-validar-la-configuración)
  - [11. Descargar los documentos](#11-descargar-los-documentos)
  - [12. Importar copias locales](#12-importar-copias-locales-obtenidas-legalmente)
  - [13. Extraer la información](#13-extraer-la-información)
  - [14. Resolver referencias](#14-resolver-referencias)
  - [15. Analizar los resultados](#15-analizar-los-resultados)
  - [16. Proponer ampliaciones](#16-proponer-ampliaciones-de-la-bibliografía)
  - [17. Añadir anotaciones](#17-añadir-anotaciones-y-revisiones-humanas)
  - [18. Construir el sitio local](#18-construir-el-sitio-local)
  - [19. Comprobar el sitio](#19-comprobar-el-sitio)
  - [20. Iniciar el sitio](#20-iniciar-el-sitio)
  - [21. Crear una versión pública](#21-crear-una-versión-pública)
  - [22. Opciones globales](#22-opciones-globales)
  - [23. Atajos de Make](#23-atajos-de-make)
  - [24. Receta completa](#24-receta-completa-para-copiar-y-pegar)
  - [25. Tabla completa de comandos](#25-tabla-completa-de-comandos)
  - [26. Códigos de salida](#26-códigos-de-salida)
  - [27. Solución de problemas](#27-solución-de-problemas)
  - [28. Recuperación y copias de seguridad](#28-recuperación-y-copias-de-seguridad)
  - [29. Privacidad y publicación segura](#29-privacidad-y-publicación-segura)
  - [30. Glosario](#30-glosario)
  - [31. Lista final de comprobación](#31-lista-final-de-comprobación)
- [Parte II. Hoja rápida](#parte-ii-hoja-rápida-de-una-página)
- [Parte III. Tabla resumen](#parte-iii-tabla-resumen-de-todos-los-comandos)
- [Parte IV. Árbol de decisión](#parte-iv-árbol-de-decisión-de-solución-de-problemas)
- [Parte V. Comprobación antes de publicar](#parte-v-lista-de-comprobación-antes-de-publicar)
- [Parte VI. Aspectos no verificados](#parte-vi-aspectos-que-no-pudieron-verificarse)

## Parte I. Manual completo

## 1. Portada

**Propósito.** Este manual explica cómo preparar, usar, revisar y publicar de forma segura una bibliografía con **bibgraph**.

**Público.** Personas sin experiencia con programación, terminales, Python ni administración de sistemas.

**Edición.** 17 de septiembre de 2026, basada en la implementación incluida en este repositorio.

**Resultado.** Al terminar, tendrá un sitio web local navegable y, si los derechos lo permiten, una versión pública separada y comprobada.

## 2. Resumen de cinco minutos

bibgraph recibe un catálogo de obras académicas. Comprueba sus datos y permisos. Descarga solo las rutas autorizadas o registra copias legales aportadas por usted. Después extrae partes de los documentos, relaciona referencias, crea grafos y rankings, y genera un sitio web sin servidor de base de datos.

```text
Catálogo → Validación → Descarga o importación → Extracción
         → Referencias → Análisis → Sitio web local
                                      └→ Versión pública permitida
```

La aplicación usa solo la biblioteca estándar de Python: no hay que instalar paquetes con `pip`. Requiere Python 3.10 o posterior. `pdftotext`, incluido en Poppler, es opcional, pero se necesita para extraer PDF automáticamente.

**Límites importantes:** bibgraph no inicia sesión, no resuelve CAPTCHA y no elude muros de pago ni controles de acceso. Que un documento pueda verse gratis no concede por sí mismo permiso para redistribuirlo. El material local se considera privado. Nunca obtenga el sitio público copiando `build/site/`.

**Estado inicial.** Este repositorio puede incluir 24 registros provisionales en `config/corpus.json`: los 20 alias semilla y cuatro partes de A5, sin títulos, autores ni URL reales. `config/dependencies.json` contiene 26 nodos, incluidas dos elecciones, pero cero relaciones. En ese estado, la aplicación puede inspeccionarse y el sitio puede construirse con `--allow-incomplete`; no producirá resultados bibliográficos útiles hasta importar el catálogo real. Las dependencias deben revisarse a mano.

## 3. Conceptos básicos

| Concepto | Explicación sencilla |
| --- | --- |
| Terminal | Ventana de texto en la que se escriben instrucciones para el equipo. En macOS se llama Terminal; en Linux puede llamarse Terminal; en Windows use WSL o Git Bash para el lanzador Bash. |
| Comando | Instrucción escrita en la terminal y confirmada con `Enter`. |
| Carpeta o directorio | Lugar que agrupa archivos. Ambos términos significan lo mismo aquí. |
| Catálogo bibliográfico | Lista estructurada de obras, enlaces, acceso y derechos. |
| Alias | Nombre corto y único para una obra, como `R0` o `A1`. |
| Recurso o *asset* | Una ruta asociada a una obra: página informativa, PDF, vista previa, etc. |
| Manifiesto | Archivo JSON revisado por personas que describe el corpus o sus dependencias. |
| Metadatos | Datos sobre una obra: título, autores, año y URL, no necesariamente su texto. |
| Grafo | Conjunto de elementos conectados; aquí representa citas o dependencias. |
| Dependencia | Regla que relaciona una lectura con otra. |
| Sitio estático | Conjunto de HTML, CSS y otros archivos que el navegador muestra sin ejecutar una aplicación remota. |
| Construcción local | Sitio en `build/site/`; puede revelar datos privados y solo debe usarse en el equipo. |
| Construcción pública | Sitio separado en `publish/`, creado desde una lista explícita de contenido permitido. |
| Código de salida | Número que el comando devuelve al terminar: `0` es éxito; otros números describen problemas. |

## 4. Requisitos previos

### Windows

`bin/bibgraph` es un programa Bash; no es un lanzador nativo de Símbolo del sistema ni PowerShell. Use **WSL** (Subsistema de Windows para Linux) o Git Bash con `python3` disponible. WSL es la opción más cercana al entorno esperado. Abra su terminal Linux y ejecute las comprobaciones de esta sección. Las rutas de WSL suelen parecerse a `/mnt/c/Users/NOMBRE/...`.

### macOS y Linux

Abra **Terminal** desde las aplicaciones. Los comandos de este manual usan Bash o un entorno compatible.

### Comprobaciones

1. Compruebe Python:

   ```bash
   python3 --version
   ```

   Debe indicar `Python 3.10` o una versión mayor. Python incluye el módulo SQLite que bibgraph usa; no basta con tener solamente el programa externo `sqlite3`.

2. Compruebe SQLite dentro de Python:

   ```bash
   python3 -c "import sqlite3; print(sqlite3.sqlite_version)"
   ```

   Debe aparecer un número de versión.

3. Compruebe la herramienta opcional de PDF:

   ```bash
   pdftotext -v
   ```

   Si no existe, bibgraph sigue funcionando, pero los PDF pueden quedar en `manual_required`. Instale el paquete Poppler con el gestor de software de su sistema.

4. Compruebe escritura desde la carpeta del proyecto con `doctor`, explicado en la sección 6. No use `sudo` como arreglo general.

5. Necesita Internet solamente para `fetch` y para `resolve --online`. La importación local, extracción, análisis y construcción pueden funcionar sin Internet una vez presentes los archivos.

## 5. Entrar en la carpeta del proyecto

`cd` significa “cambiar de carpeta”. Sustituya `RUTA/AL/PROYECTO` por la ubicación real.

En macOS, Linux, WSL o Git Bash:

```bash
cd RUTA/AL/PROYECTO
```

Ejemplo, solo si el proyecto está realmente allí:

```bash
cd /workspace/top
```

En PowerShell, `cd C:\ruta\al\proyecto` cambia de carpeta, pero después deberá abrir WSL/Git Bash para usar `./bin/bibgraph`. En WSL una ruta de Windows puede escribirse así:

```bash
cd /mnt/c/Users/NOMBRE/ruta/al/proyecto
```

Compruebe la ubicación:

```bash
pwd
```

```bash
test -f bin/bibgraph -a -f config/corpus.json && echo "Carpeta correcta"
```

El segundo comando debe mostrar `Carpeta correcta`.

## 6. Primera comprobación

```bash
./bin/bibgraph doctor
```

`doctor` crea y borra pequeños archivos de prueba para verificar escritura en `config`, `data`, `reports`, `private`, `cache` y `build`. También informa la versión de Python, SSL, SQLite, `pdftotext`, variables de entorno y presencia de los archivos de configuración. No imprime valores secretos.

Python 3.10+, SQLite utilizable y las seis ubicaciones escribibles son obligatorios. `pdftotext` es opcional. SSL es necesario para descargas HTTPS fiables.

La salida humana comienza con `bibgraph doctor` y muestra cada capacidad. `ABSENT` para `pdftotext` es una limitación, no un bloqueo general. Corrija Python con una instalación actual, SQLite instalando una distribución completa de Python, y permisos dando escritura a su usuario sobre su propia copia del proyecto.

Forma equivalente, útil si el lanzador Bash no se puede ejecutar:

```bash
PYTHONPATH=src python3 -m bibgraph doctor
```

En ambos casos sitúese primero en la raíz del proyecto. La segunda forma configura manualmente dónde Python encuentra bibgraph.

## 7. Preparar la bibliografía

Cree `phase-1-access-verification.md` en la raíz. Es un archivo Markdown: texto sencillo con una tabla delimitada por barras verticales. El importador busca la primera tabla cuya cabecera contenga todas las columnas obligatorias; no es un importador Markdown universal.

### Ejemplo completo y copiable

```markdown
| ID | Title | Type | Access | URL | Role | Intent | Authors | Year | License | License Evidence | Observed | Notes | Container | Members |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| R0 | Guía de ejemplo | article | open | https://example.org/record | landing | metadata_only | Ana Pérez; Luis Soto | 2020 | CC BY 4.0 | https://example.org/license | Consultado y visible | Página descriptiva | | |
| R0 | Guía de ejemplo | article | open | https://example.org/document.pdf | fulltext | required | Ana Pérez; Luis Soto | 2020 | CC BY 4.0 | https://example.org/license | PDF accesible | Texto completo | | |
| A1 | Libro sin descarga autorizada | book | purchase | https://example.org/book | landing | manual | Carmen Ruiz | 2018 | | | Solo compra | Obtener legalmente por biblioteca o compra | | |
| A5 | Colección de secuencias | collection | open | https://example.org/collection | landing | metadata_only | Equipo Ejemplo | 2021 | CC0 | https://example.org/rights | Catálogo visible | Contenedor | | A5.1, A5.2 |
| A5.1 | Primera secuencia | sequence | open | https://example.org/sequence-1.html | fulltext | required | Equipo Ejemplo | 2021 | CC0 | https://example.org/rights | Texto visible | Miembro uno | A5 | |
| A5.2 | Segunda secuencia | sequence | preview | https://example.org/sequence-2 | preview | manual | Equipo Ejemplo | 2021 | | | Vista previa | Requiere copia legal | A5 | |
```

Las URL `example.org` son ejemplos: sustitúyalas por fuentes reales y revisadas.

### Significado de las columnas

| Nombre | Obligatoria | Propósito | Valores admitidos | Ejemplo | Error frecuente |
| --- | --- | --- | --- | --- | --- |
| `ID` | Sí | Alias que agrupa filas de la misma obra. | Texto no vacío. | `R0` | Cambiar el ID entre dos URL de una obra. |
| `Title` | Sí como columna | Título; puede estar vacío, pero queda sin verificar. | Texto. | `Guía` | Usar `|` dentro de una celda. |
| `Type` | Sí | Clase de obra. | `article`, `book`, `notes`, `sequence`, `web_page`, `collection` | `article` | Escribir un valor libre como `paper`. |
| `Access` | Sí | Acceso observado. | `open`, `preview`, `borrow`, `purchase`, `institutional`, `unknown` | `open` | Confundir acceso con licencia. |
| `URL` | Sí como columna | Dirección del recurso; si queda vacía no se crea recurso. | URL HTTP(S), sola o enlace Markdown. | `https://.../doc.pdf` | Poner dos URL en una celda. |
| `Role` | Sí | Función de esa URL. | `landing`, `fulltext`, `metadata`, `mirror`, `preview`, `borrow` | `fulltext` | Llamar `fulltext` a una portada. |
| `Intent` | Sí | Acción de adquisición. | `required`, `fallback`, `metadata_only`, `manual`, `ignore` | `required` | Marcar como requerida una ruta no autorizada. |
| `Authors` | No | Autores de la obra. | Nombres separados por punto y coma. | `Ana Pérez; Luis Soto` | Separar por coma, que puede pertenecer al nombre. |
| `Year` | No | Año. | Exactamente cuatro cifras o vacío. | `2020` | Escribir una fecha completa; se importaría como `null`. |
| `License` | No | Nombre de la licencia. | Texto revisado. | `CC BY 4.0` | Suponerla por el acceso abierto. |
| `License Evidence` | No | URL que demuestra la licencia. | Una URL extraíble. | `https://.../license` | Escribir evidencia sin URL. |
| `Observed` | No | Nota sobre lo observado. | Texto. | `PDF accesible` | Confundirla con la fecha; la fecha general va en `--observed-on`. |
| `Notes` | No | Nota libre. | Texto sin barras verticales. | `Copia en biblioteca` | Incluir secretos o datos personales. |
| `Container` | No | Alias de la colección que contiene esta obra. | Alias. | `A5` | Referir un contenedor inexistente. |
| `Members` | No | Miembros de una colección. | Alias separados por comas. | `A5.1, A5.2` | Separarlos con punto y coma. |

Para una sola URL use una fila. Para varias URL repita el mismo `ID`, una fila por recurso: por ejemplo una fila `landing` con `metadata_only` y otra `fulltext` con `required`. La primera aparición de un ID fija los datos de la obra; revise que las filas repetidas sean coherentes. Una obra sin permiso de descarga debe usar, por ejemplo, `purchase` y `manual`, no `required`. La evidencia de licencia debe ser una URL en `License Evidence`.

**Advertencia:** al importar, `open` permite almacenamiento local, pero no activa `publish_abstract` ni `publish_fulltext`. Acceso abierto no se convierte automáticamente en permiso de publicación.

## 8. Importar el catálogo

1. Pruebe sin guardar. Sustituya `AAAA-MM-DD` por la fecha pasada o actual en que verificó el acceso:

   ```bash
   ./bin/bibgraph import-catalogue phase-1-access-verification.md --observed-on AAAA-MM-DD --dry-run
   ```

   `--dry-run` imprime el JSON resultante y no reemplaza el catálogo.

2. Antes de importar definitivamente, respalde el archivo actual:

   ```bash
   cp config/corpus.json config/corpus.json.backup
   ```

3. Importe:

   ```bash
   ./bin/bibgraph import-catalogue phase-1-access-verification.md --observed-on AAAA-MM-DD
   ```

   Por defecto reemplaza atómicamente `config/corpus.json`. Debe informar cuántas obras y recursos importó. Abra el archivo con un editor y busque sus títulos, alias y URL.

4. Para no tocar el catálogo predeterminado:

   ```bash
   ./bin/bibgraph import-catalogue ARCHIVO.md --output RUTA/AL/CORPUS.json
   ```

`--observed-on` registra cuándo se observó el estado de acceso; no afirma que sea permanente. Si faltan los alias semilla esperados, la importación termina pero muestra una advertencia. `validate` también lo reflejará. Una cabecera o separador incorrectos causa rechazo indicando las columnas requeridas. El importador acepta exclusivamente una tabla con barras, una fila separadora de guiones y las columnas indicadas.

## 9. Configurar las dependencias

Abra `config/dependencies.json` con un editor de texto. Es JSON: claves entre comillas, dos puntos entre clave y valor, y comas entre elementos. `nodes` enumera nodos; `edges` contiene relaciones como esta:

```json
{
  "from": "R0",
  "to": "A1",
  "type": "prerequisite",
  "note": "R0 debe leerse antes que A1."
}
```

`from` es el prerrequisito y `to` el documento dependiente.

| Tipo | Uso | Afecta al orden |
| --- | --- | --- |
| `prerequisite` | Lectura necesaria antes de otra. | Sí. |
| `backup` | Alternativa o respaldo. | No. |
| `validates` | Una obra ayuda a comprobar otra. | No. |
| `conditional` | Ruta que depende de una condición. | Sí. |
| `orientation` | Lectura de orientación previa. | Sí. |
| `historical` | Antecedente histórico. | Sí. |

Los cuatro tipos que afectan al orden no deben formar ciclos: un ciclo exigiría leer A antes de B y B antes de A.

`config/reading-profile.json` elige una opción para los nodos de tipo `choice`. Un valor `null` significa que la decisión sigue deliberadamente sin resolver; no es un error tipográfico. Sustitúyalo solo por uno de los alias incluidos en `options`, después de una revisión humana.

## 10. Validar la configuración

```bash
./bin/bibgraph validate
```

```bash
./bin/bibgraph validate --strict
```

Un **error** invalida el manifiesto y devuelve código 3. Una **advertencia** describe una carencia o riesgo sin bloquear el modo normal. Con `--strict`, cualquier advertencia también hace fallar la validación con código 3. El informe legible queda en `reports/validate.md` y el registro estructurado en `reports/validate.jsonl`.

Los mensajes pueden referirse, por ejemplo, a metadatos no verificados, alias semilla ausentes, un grafo sin relaciones o una referencia de nodo incorrecta. Esos son ejemplos de categorías, no copias prometidas de una salida. Lea la ubicación y el texto de cada entrada, corrija el archivo indicado y repita `validate`.

## 11. Descargar los documentos

Uso habitual:

```bash
./bin/bibgraph fetch
```

```bash
./bin/bibgraph fetch --strict
```

`--strict` detiene el recorrido ante el primer recurso obligatorio fallido. Para recoger todos los fallos:

```bash
./bin/bibgraph fetch --keep-going
```

Limite por alias; la opción se puede repetir:

```bash
./bin/bibgraph fetch --alias R0 --alias A1
```

Exija texto completo para toda obra no contenedora:

```bash
./bin/bibgraph fetch --require-fulltext-all
```

Cambie la pausa entre solicitudes, en segundos:

```bash
./bin/bibgraph fetch --delay 2.5
```

Opciones avanzadas, no recomendadas de forma habitual:

```bash
./bin/bibgraph fetch --allow-http
```

HTTP no cifra el tráfico. Úselo solo si comprende el riesgo y la fuente no ofrece HTTPS.

```bash
./bin/bibgraph fetch --allow-private-host 127.0.0.1
```

Se puede repetir para hosts concretos. Permite conexiones a redes no públicas y reduce la protección contra solicitudes internas. Nunca lo use como arreglo general.

```bash
./bin/bibgraph fetch --no-robots
```

Omite la orientación de `robots.txt` y registra la decisión. No debe ser la primera solución ante un bloqueo; solicite permiso o aporte una copia legal.

Identifíquese de forma responsable ante servidores y Crossref:

```bash
export BIBGRAPH_CONTACT_EMAIL="nombre@example.org"
```

Este formato sirve en Bash, zsh, WSL y Git Bash y dura hasta cerrar la terminal. En `fish`: `set -x BIBGRAPH_CONTACT_EMAIL nombre@example.org`. En PowerShell, para una invocación directa equivalente de Python: `$env:BIBGRAPH_CONTACT_EMAIL="nombre@example.org"`.

Solo se solicitan recursos con intención explícita. `ignore` no se solicita; `manual` entra en cola manual; `metadata_only` no solicita el texto. Si `local_storage_allowed` es falso, bibgraph no guarda la copia. Los archivos finales quedan bajo `private/raw/`; los importados manualmente, bajo `private/manual-import/`. `data/state.sqlite3` y los informes `reports/fetch-FECHA.md`/`.jsonl` registran estado, URL, redirecciones, tamaño, tipo, hash SHA-256, procedencia y errores sin publicar rutas absolutas.

La descarga acepta solo HTTP(S), rechaza credenciales incrustadas, HTTP por defecto y direcciones privadas. Respeta `robots.txt`, limita cada cuerpo a 64 MiB, sigue como máximo cinco redirecciones, aplica tiempo de espera y reintenta fallos transitorios hasta tres intentos. `429` y ciertos errores de servidor pueden reintentarse respetando `Retry-After`; 401, 403 y 404 no. Un tipo declarado o firma de archivo incompatible produce fallo de integridad; una página de acceso recibida en lugar de PDF también. No intente evadir autenticación, CAPTCHA ni pago.

## 12. Importar copias locales obtenidas legalmente

```bash
./bin/bibgraph import ALIAS RUTA/AL/ARCHIVO
```

El rol predeterminado es `fulltext`. Puede indicarlo:

```bash
./bin/bibgraph import ALIAS RUTA/AL/ARCHIVO --role ROL
```

Ejemplos:

```bash
./bin/bibgraph import R0 documentos/articulo.pdf
```

```bash
./bin/bibgraph import A1 documentos/pagina.html --role fulltext
```

```bash
./bin/bibgraph import B2 documentos/notas.txt --role fulltext
```

El alias debe existir. El comando detecta PDF, HTML, XML o texto, copia el archivo a `private/manual-import/`, calcula su SHA-256 y lo registra como `user_supplied`: aportado por el usuario, no descargado ni verificado por bibgraph. El rol es texto libre en este subcomando; use normalmente uno de los roles controlados para mantener coherencia. El archivo sigue siendo privado y nunca se publica por defecto.

## 13. Extraer la información

```bash
./bin/bibgraph extract
```

```bash
./bin/bibgraph extract --strict
```

```bash
./bin/bibgraph extract --alias R0 --alias A1
```

```bash
./bin/bibgraph extract --pdf-timeout 180
```

Procesa HTML, XML/JATS, texto y PDF. Para PDF llama a `pdftotext`; `--pdf-timeout` fija cuántos segundos puede tardar cada conversión. Intenta obtener título, resumen, introducción, jerarquía de secciones, conclusión y referencias. Conserva procedencia y confianza.

Cada documento estructurado se guarda en `data/documents/`; el texto privado puede quedar en `private/text/`. El resumen está en `reports/extract.md` y `.jsonl`. La cola manual enumera obras que requieren intervención. Sin `pdftotext`, un PDF no se interpreta a medias: sus campos quedan `manual_required`. Con `--strict`, cualquier obra de la cola manual produce código 2.

| Estado | Significado |
| --- | --- |
| `present` | Se encontró contenido con procedencia. |
| `not_present` | El campo era pertinente, pero no se encontró. |
| `not_applicable` | Ese campo no corresponde al tipo de obra. |
| `manual_required` | Hace falta una herramienta o revisión humana. |
| `failed` | Un error impidió extraerlo. |

## 14. Resolver referencias

```bash
./bin/bibgraph resolve
```

```bash
./bin/bibgraph resolve --strict
```

```bash
./bin/bibgraph resolve --online
```

```bash
./bin/bibgraph resolve --no-discovery
```

Resolver significa relacionar una referencia escrita dentro de un documento con una obra identificada. bibgraph acepta automáticamente solo una coincidencia fuerte y única. Las ambiguas o no resueltas quedan en la cola de revisión; `--strict` devuelve código 2 si alguna queda totalmente sin resolver.

Por defecto, una referencia fiable que no pertenece al catálogo puede convertirse en un nodo descubierto, solo de metadatos. `--no-discovery` impide crear estos candidatos. `--online` permite consultas opcionales a Crossref y, por tanto, usa Internet; configure `BIBGRAPH_CONTACT_EMAIL`. Ejecute siempre `extract` antes porque las referencias salen de los documentos extraídos. El resultado principal queda en `data/references.jsonl` y el informe en `reports/resolve.md`.

## 15. Analizar los resultados

```bash
./bin/bibgraph analyze
```

El **grafo de citas** muestra quién cita a quién. El **acoplamiento bibliográfico** aproxima qué obras comparten referencias. Las **agrupaciones** reúnen obras relacionadas. El **ranking** combina medidas publicadas en `config/ranking.json`; la **prioridad de lectura** sugiere un orden, no una verdad. El **análisis de sensibilidad** muestra si pequeños cambios de pesos alteran la lista. Los **índices de autores** agrupan identidades normalizadas.

El comando lee `data/references.jsonl`, vuelve a generar grafos y `data/survey.json`, y exporta datos derivados. Las métricas no reemplazan la lectura humana ni prueban que una obra apoye o contradiga una afirmación.

## 16. Proponer ampliaciones de la bibliografía

```bash
./bin/bibgraph promote
```

```bash
./bin/bibgraph promote --max-new 10 --min-citations 2 --year-from 2015 --year-to 2025
```

`--max-new` limita candidatos; `--min-citations` exige que los cite un mínimo de obras del corpus; los dos límites de año filtran el intervalo. La propuesta queda en `reports/promotion-queue.md` y `.jsonl`. No descarga, no modifica `config/corpus.json` y necesita revisión humana de identidad, pertinencia, acceso y derechos.

## 17. Añadir anotaciones y revisiones humanas

El método de S. Keshav propone tres pasadas: la primera identifica estructura y panorama; la segunda examina contenido, evidencia y referencias; la tercera reconstruye y critica el trabajo en profundidad. bibgraph automatiza parte de la primera y conserva la revisión humana.

En una página local de obra aparece un bloque JSON prellenado que puede copiarse a `ARCHIVO.json`; con JavaScript habilitado también hay descarga progresiva. El esquema completo no está formalizado como un archivo de esquema. La implementación solo exige que la raíz sea un objeto JSON y valida `pass_status` si aparece.

Ejemplo mínimo seguro:

```json
{
  "pass_status": "pass_1"
}
```

Valores: `unread`, `pass_1`, `pass_2`, `pass_3`.

```bash
./bin/bibgraph annotate ALIAS ARCHIVO.json
```

El alias debe existir. El registro se normaliza en `annotations/ALIAS.json` y también se registra en `data/state.sqlite3`. Para corregir JSON inválido, compruebe comillas dobles, comas y llaves, y valide con:

```bash
python3 -m json.tool ARCHIVO.json
```

Las anotaciones son privadas salvo que contengan explícitamente `"publish": true` y se cree una construcción pública.

## 18. Construir el sitio local

```bash
./bin/bibgraph build-site --local
```

El destino normal es `build/site/`. Puede cambiarlo:

```bash
./bin/bibgraph build-site --local --output RUTA/DE/SALIDA
```

Si el catálogo fuente no fue suministrado o el grafo no tiene relaciones, la construcción se niega con código 2. Para inspeccionar un resultado incompleto:

```bash
./bin/bibgraph build-site --local --allow-incomplete
```

La salida advertirá cada motivo y el sitio mostrará distintivos visibles de incompletitud. El sitio local puede contener extractos, anotaciones y procedencia privada. **Advertencia:** no lo suba a Internet y no lo copie para fabricar la versión pública.

## 19. Comprobar el sitio

```bash
./bin/bibgraph check-site build/site
```

```bash
./bin/bibgraph check-site publish --public
```

Comprueba enlaces internos, anclas, rutas que escapan de la raíz y archivos ausentes. Con `--public` también busca carpetas privadas, PDF y bases de datos prohibidos, rutas locales absolutas y valores con apariencia de secretos. La construcción pública aplica además un presupuesto de 100 MiB al crearla; `check-site` no vuelve a calcular ese presupuesto. El informe queda en `reports/check-site.md` y `.jsonl`.

## 20. Iniciar el sitio

1. Construya y compruebe el sitio local.
2. Inicie el servidor:

   ```bash
   python3 -m http.server --bind 127.0.0.1 --directory build/site 8000
   ```

3. La terminal quedará ocupada: es normal; está atendiendo el sitio.
4. Abra [el sitio local en `http://127.0.0.1:8000/`](http://127.0.0.1:8000/) con su navegador.
5. Para detenerlo, vuelva a la terminal y pulse `Ctrl+C`.
6. Si 8000 está ocupado, use otro puerto:

   ```bash
   python3 -m http.server --bind 127.0.0.1 --directory build/site 8080
   ```

   Abra entonces `http://127.0.0.1:8080/`.

`127.0.0.1` significa “solo este equipo”. No cambie a una dirección abierta a toda la red si no comprende el acceso y la privacidad.

Atajos equivalentes:

```bash
make serve
```

```bash
make serve PORT=8080
```

## 21. Crear una versión pública

```bash
./bin/bibgraph build-site --public
```

```bash
./bin/bibgraph check-site publish --public
```

O use el atajo que ejecuta ambos en orden:

```bash
make publish
```

`build/site/` es local y puede contener material privado. `publish/` parte de una lista vacía y permite solo metadatos autorizados, pasajes autorizados, grafos derivados, enlaces externos y anotaciones con `"publish": true`. Los títulos y referencias dependen de `publish_metadata`. Resumen requiere `publish_abstract`; introducción y conclusión requieren `publish_fulltext`. Los pasajes requieren además `license_evidence_url`.

El informe `reports/publication.md` enumera contenido incluido y retenido, licencia y evidencia. Poder leer algo en la Web no concede redistribución. Ejecute siempre `check-site publish --public` antes de publicar y publique solo el contenido de `publish/`.

## 22. Opciones globales

Las opciones globales van **antes** del subcomando porque así las interpreta `argparse`:

```bash
./bin/bibgraph --root RUTA/AL/PROYECTO validate
```

```bash
./bin/bibgraph --json validate
```

```bash
./bin/bibgraph --root RUTA/AL/PROYECTO --json doctor
```

`--root` permite operar sobre otro proyecto sin cambiar de carpeta, aunque el lanzador sigue perteneciendo a este repositorio. `--json` ofrece salida estructurada para herramientas; una persona normalmente preferirá la salida predeterminada. La implementación usa `--json` principalmente en `doctor`, `validate`, `fetch`, `extract` y `check-site`; no todos los manejadores cambian su salida con esta opción global.

## 23. Atajos de Make

`make` es una herramienta opcional y puede no estar instalada. Estos atajos llaman a Python con `PYTHONPATH=src`; no contienen una segunda implementación.

| Atajo | Equivale o sirve para | Modifica archivos |
| --- | --- | --- |
| `make help` | Lista objetivos documentados. | No, salvo lectura. |
| `make doctor` | `doctor`. | Crea carpetas y pruebas temporales de escritura. |
| `make validate` | `validate`. | Sí: informes. |
| `make fetch` | `fetch --strict`. | Sí: privados, estado e informes. |
| `make extract` | `extract --strict`. | Sí: documentos, texto e informes. |
| `make resolve` | `resolve --strict`. | Sí: referencias, análisis e informes. |
| `make analyze` | `analyze`. | Sí: datos derivados. |
| `make site` | `build-site --local`. | Sí: `build/site/`. |
| `make check-site` | `check-site build/site`. | Sí: informe. |
| `make serve` | Servidor local en `PORT`, 8000 por defecto. | No modifica el sitio. |
| `make test` | `python3 -m unittest`. | Puede crear temporales y caché de Python. |
| `make publish` | Construye `publish/` y lo comprueba. | Sí: publicación e informes. |
| `make clean` | Borra `build`, `publish` y todos los directorios `__pycache__` bajo el proyecto. | **Sí, elimina esos elementos.** |

## 24. Receta completa para copiar y pegar

Ejecute un bloque, lea el resultado y solo entonces continúe.

```bash
cd RUTA/AL/PROYECTO
```

```bash
./bin/bibgraph doctor
```

```bash
./bin/bibgraph import-catalogue phase-1-access-verification.md --observed-on AAAA-MM-DD --dry-run
```

```bash
cp config/corpus.json config/corpus.json.backup
```

```bash
./bin/bibgraph import-catalogue phase-1-access-verification.md --observed-on AAAA-MM-DD
```

Ahora abra y revise `config/dependencies.json` y `config/reading-profile.json`.

```bash
./bin/bibgraph validate --strict
```

```bash
export BIBGRAPH_CONTACT_EMAIL="nombre@example.org"
```

```bash
./bin/bibgraph fetch --keep-going
```

Si el informe pide una copia legal, impórtela una por una:

```bash
./bin/bibgraph import ALIAS RUTA/AL/ARCHIVO.pdf
```

```bash
./bin/bibgraph extract
```

```bash
./bin/bibgraph resolve
```

```bash
./bin/bibgraph analyze
```

```bash
./bin/bibgraph build-site --local
```

```bash
./bin/bibgraph check-site build/site
```

```bash
python3 -m http.server --bind 127.0.0.1 --directory build/site 8000
```

Abra `http://127.0.0.1:8000/` y detenga el servidor con `Ctrl+C`.

## 25. Tabla completa de comandos

| Comando | Finalidad | Lee | Crea o modifica | Internet | Riesgo o precaución | Resultado esperado | Siguiente comando |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `doctor` | Diagnosticar el entorno. | Entorno y presencia de `config/`. | Carpetas y sondas temporales. | No. | No revela valores secretos. | Lista de capacidades. | `import-catalogue` o `validate`. |
| `validate [--strict]` | Validar manifiestos y derechos. | `config/corpus.json`, dependencias, perfil. | `reports/validate.*`. | No. | Estricto convierte avisos en fallo. | Conteos e incidencias. | `fetch`. |
| `import-catalogue ...` | Convertir la tabla Markdown. | Archivo Markdown. | `config/corpus.json` o `--output`; nada con `--dry-run`. | No. | Puede reemplazar el catálogo. | Obras y recursos importados. | Revisar dependencias y `validate`. |
| `fetch [...]` | Adquirir rutas autorizadas. | Configuración y estado. | `private/raw/`, SQLite e informes por ejecución. | Sí. | No debilitar protecciones sin justificación. | Estado por recurso. | `import` o `extract`. |
| `import ALIAS ARCHIVO` | Registrar copia legal. | Catálogo y archivo local. | `private/manual-import/`, SQLite. | No. | Copiar solo material obtenido legalmente. | Hash y ruta privada. | `extract`. |
| `extract [...]` | Extraer estructura y referencias. | Artefactos, catálogo, SQLite. | `data/documents/`, `private/text/`, informe. | No. | PDF requiere `pdftotext`. | Estados por campo y cola manual. | `resolve`. |
| `resolve [...]` | Relacionar referencias. | Documentos y catálogo. | `data/references.jsonl`, grafos, encuesta, informe. | Solo con `--online`. | Crossref es opcional; revisar ambigüedades. | Coincidencias y cola. | `analyze`. |
| `analyze` | Regenerar grafos y rankings. | `data/references.jsonl`, ranking, revisiones. | Datos derivados y `data/survey.json`. | No. | Las métricas no son juicio académico. | Conteos de grafos y autores. | `build-site`. |
| `promote [...]` | Proponer obras descubiertas. | Referencias y configuración. | `reports/promotion-queue.*`. | No. | Propuesta, no incorporación. | Lista limitada de candidatos. | Revisión humana. |
| `annotate ALIAS ARCHIVO.json` | Registrar lectura humana. | Catálogo y JSON. | `annotations/ALIAS.json`, SQLite. | No. | Privada salvo `publish: true`. | Estado de pasada registrado. | `build-site`. |
| `build-site --local/--public` | Generar sitio. | Configuración, datos, informes y anotaciones. | `build/site/` o `publish/`; informe público. | No. | Local no debe publicarse. | Archivos HTML/CSS/JS estáticos. | `check-site`. |
| `check-site RUTA [--public]` | Revisar enlaces y fugas. | Sitio indicado. | `reports/check-site.*`. | No. | Use `--public` sobre `publish`. | Cero errores antes de usar/publicar. | Servir o publicar. |

## 26. Códigos de salida

| Código | Significado |
| --- | --- |
| `0` | Operación completada. |
| `2` | Adquisición o extracción incompleta. También se usa para otros resultados incompletos, como sitio no comprobable. |
| `3` | Manifiesto o entrada de configuración inválida. |
| `4` | Fallo de integridad o tipo de contenido. |

Si coinciden varios, la prioridad es `3 > 4 > 2 > 0`. Un valor distinto de cero no significa que todo sea inútil: puede haber archivos válidos e informes con los detalles. Revise siempre `reports/`.

## 27. Solución de problemas

Cada caso conserva la misma plantilla. No publique URL privadas, correos, claves, anotaciones ni documentos al pedir ayuda.

### 1. El lanzador muestra `Permission denied`

#### Síntoma
La terminal rechaza `./bin/bibgraph` con `Permission denied`.

#### Significado
El archivo no tiene permiso de ejecución o la unidad no permite ejecutar archivos.

#### Comprobación
```bash
test -x bin/bibgraph && echo ejecutable
```

#### Solución paso a paso
1. Confirme que está en la raíz. 2. Use `chmod u+x bin/bibgraph`. 3. Si la unidad bloquea ejecución, use `PYTHONPATH=src python3 -m bibgraph doctor`.

#### Cuándo pedir ayuda
Comparta el error, `pwd` y `stat bin/bibgraph`; oculte nombres privados de carpetas.

### 2. No existe `python3`

#### Síntoma
Ve `python3: command not found`.

#### Significado
Python no está instalado o no está en la ruta de programas.

#### Comprobación
```bash
command -v python3
```

#### Solución paso a paso
1. Instale Python 3.10+ desde el sistema o python.org. 2. Cierre y abra la terminal. 3. Repita `python3 --version`.

#### Cuándo pedir ayuda
Indique sistema operativo y resultado del comando, sin datos personales.

### 3. Python es anterior a 3.10

#### Síntoma
`doctor` dice `TOO OLD`.

#### Significado
La sintaxis y funciones requeridas no están disponibles.

#### Comprobación
```bash
python3 --version
```

#### Solución paso a paso
1. Instale una versión admitida. 2. Asegure que `python3` apunta a ella. 3. Repita `doctor`.

#### Cuándo pedir ayuda
Comparta las rutas de `command -v python3` y la versión.

### 4. SQLite no está disponible

#### Síntoma
`doctor` muestra SQLite `UNUSABLE`.

#### Significado
El módulo SQLite de esa instalación de Python falta o falla.

#### Comprobación
```bash
python3 -c "import sqlite3; print(sqlite3.sqlite_version)"
```

#### Solución paso a paso
1. Reinstale una distribución completa de Python. 2. No borre `data/state.sqlite3`. 3. Repita `doctor`.

#### Cuándo pedir ayuda
Comparta el error completo y versión de Python; no comparta la base de datos.

### 5. Una carpeta no permite escritura

#### Síntoma
`doctor` marca `config`, `data`, `reports`, `private`, `cache` o `build` como no escribible.

#### Significado
Su usuario no puede crear archivos allí.

#### Comprobación
```bash
./bin/bibgraph doctor
```

#### Solución paso a paso
1. Mueva una copia del proyecto a una carpeta de su usuario. 2. Revise propietario y permisos. 3. Evite `sudo`. 4. Repita `doctor`.

#### Cuándo pedir ayuda
Comparta solo la fila afectada y permisos; oculte la ruta personal.

### 6. Falta `pdftotext`

#### Síntoma
`doctor` muestra `pdftotext ABSENT`.

#### Significado
La extracción automática de PDF no está disponible.

#### Comprobación
```bash
pdftotext -v
```

#### Solución paso a paso
1. Instale Poppler con el gestor oficial del sistema. 2. Abra otra terminal. 3. Repita `doctor` y `extract`.

#### Cuándo pedir ayuda
Indique sistema y salida de `doctor`; no adjunte el PDF si es privado.

### 7. Un PDF queda `manual_required`

#### Síntoma
El informe de extracción envía una obra a la cola manual.

#### Significado
Puede faltar `pdftotext`, agotarse su tiempo o no haber una copia procesable.

#### Comprobación
Revise `reports/extract.md` y ejecute `./bin/bibgraph doctor`.

#### Solución paso a paso
1. Lea el motivo exacto. 2. Instale `pdftotext` si falta. 3. Si es lento, use `--pdf-timeout 180`. 4. Revise manualmente sin eludir protecciones.

#### Cuándo pedir ayuda
Comparta alias, motivo y versión de Poppler, no el contenido privado.

### 8. No se encuentra el archivo del catálogo

#### Síntoma
Se informa que `phase-1-access-verification.md` no existe.

#### Significado
La ruta es incorrecta o está en otra carpeta.

#### Comprobación
```bash
test -f phase-1-access-verification.md && echo encontrado
```

#### Solución paso a paso
1. Entre en la raíz. 2. Mueva o guarde allí el archivo. 3. O indique su ruta real en el comando.

#### Cuándo pedir ayuda
Comparta `pwd` y el nombre del archivo, ocultando rutas privadas.

### 9. No se encuentra una tabla Markdown válida

#### Síntoma
El importador dice que no halló la tabla del catálogo.

#### Significado
No existe una tabla con barras, separador y todas las cabeceras requeridas.

#### Comprobación
Compare el archivo con el ejemplo de la sección 7.

#### Solución paso a paso
1. Copie la cabecera exacta. 2. Añada la fila de guiones. 3. Evite barras dentro de celdas. 4. Pruebe con `--dry-run`.

#### Cuándo pedir ayuda
Comparta solo cabecera y una fila anonimizadas.

### 10. Falta una columna obligatoria

#### Síntoma
La importación enumera columnas necesarias que no encontró.

#### Significado
La cabecera no incluye `ID`, `Title`, `Type`, `Access`, `URL`, `Role` o `Intent`.

#### Comprobación
Revise la primera fila de la tabla.

#### Solución paso a paso
1. Añada la columna faltante. 2. Mantenga una celda por columna en cada fila. 3. Repita la prueba seca.

#### Cuándo pedir ayuda
Comparta la cabecera exacta.

### 11. Hay un valor de vocabulario no permitido

#### Síntoma
El error menciona `Type`, `Access`, `Role` o `Intent` y enumera valores.

#### Significado
La celda no coincide con el vocabulario controlado.

#### Comprobación
Revise la tabla de la sección 7.

#### Solución paso a paso
1. Localice fila y alias indicados. 2. Sustituya por un valor exacto permitido. 3. Repita `--dry-run`.

#### Cuándo pedir ayuda
Comparta campo, valor y lista indicada; oculte la URL.

### 12. Faltan alias esperados

#### Síntoma
La importación advierte que faltan alias semilla.

#### Significado
El archivo no contiene todos los 20 alias previstos (`R0`, A1–A7, B1–B6, C1–C5, D1).

#### Comprobación
```bash
./bin/bibgraph validate
```

#### Solución paso a paso
1. Compare la fuente con la lista. 2. Corrija IDs o agregue filas reales. 3. No invente metadatos. 4. Reimporte.

#### Cuándo pedir ayuda
Comparta solo la lista de alias ausentes.

### 13. El manifiesto es inválido

#### Síntoma
Un comando se niega a continuar con código 3.

#### Significado
La configuración no se pudo leer o contiene errores de modelo.

#### Comprobación
```bash
./bin/bibgraph validate
```

#### Solución paso a paso
1. Lea cada error. 2. Corrija el archivo y ubicación indicados. 3. Valide JSON con `python3 -m json.tool RUTA`. 4. Repita.

#### Cuándo pedir ayuda
Comparta errores y fragmento anonimizado, nunca todo el corpus privado.

### 14. `validate --strict` falla por advertencias

#### Síntoma
La validación normal pasa, pero la estricta devuelve 3.

#### Significado
El modo estricto trata toda advertencia como fallo.

#### Comprobación
Revise `reports/validate.md`.

#### Solución paso a paso
1. Atienda cada advertencia. 2. Complete metadatos o relaciones reales. 3. No silencie avisos inventando datos. 4. Repita el modo estricto.

#### Cuándo pedir ayuda
Comparta códigos y mensajes de advertencia.

### 15. Existe un ciclo en dependencias

#### Síntoma
La validación informa un ciclo de orden.

#### Significado
Las relaciones exigen un orden imposible.

#### Comprobación
Revise `edges` en `config/dependencies.json` y `reports/validate.md`.

#### Solución paso a paso
1. Dibuje las flechas del ciclo. 2. Confirme `from` y `to`. 3. Elimine o cambie solo la relación conceptualmente incorrecta. 4. Valide.

#### Cuándo pedir ayuda
Comparta los alias y tipos del ciclo, no notas privadas.

### 16. Una dependencia apunta a un alias inexistente

#### Síntoma
La validación no reconoce un extremo de una relación.

#### Significado
`from` o `to` no coincide con ningún nodo.

#### Comprobación
Compare `edges` con `nodes` en `config/dependencies.json`.

#### Solución paso a paso
1. Corrija la errata del alias. 2. Si la obra es real, añada/revise su nodo y corpus. 3. No deje nodos ficticios. 4. Valide.

#### Cuándo pedir ayuda
Comparta la relación y los IDs de nodos.

### 17. El alias de `import` no existe

#### Síntoma
`import` responde `unknown alias`.

#### Significado
La copia no se puede asociar a una obra del catálogo.

#### Comprobación
Busque el alias en `config/corpus.json`.

#### Solución paso a paso
1. Corrija mayúsculas y escritura. 2. Importe primero el catálogo si falta. 3. Valide. 4. Repita `import`.

#### Cuándo pedir ayuda
Comparta el alias, no el archivo.

### 18. El archivo local no existe

#### Síntoma
`import` no puede abrir `RUTA/AL/ARCHIVO`.

#### Significado
La ruta está mal escrita o no es visible desde ese entorno.

#### Comprobación
```bash
test -f RUTA/AL/ARCHIVO && echo encontrado
```

#### Solución paso a paso
1. Use la ruta exacta. 2. Entre en la carpeta apropiada o use ruta absoluta. 3. En WSL convierta la ruta a `/mnt/...`. 4. Repita.

#### Cuándo pedir ayuda
Comparta el tipo de ruta, ocultando nombres personales.

### 19. Una URL HTTP es rechazada

#### Síntoma
El informe dice que HTTP simple no fue aprobado.

#### Significado
La conexión no estaría cifrada.

#### Comprobación
Revise la URL del recurso en `config/corpus.json`.

#### Solución paso a paso
1. Busque una URL HTTPS oficial. 2. Corrija el catálogo. 3. Solo si no existe y acepta el riesgo, use conscientemente `--allow-http`.

#### Cuándo pedir ayuda
Comparta dominio y mensaje, no parámetros privados.

### 20. La URL apunta a una dirección privada o local

#### Síntoma
`fetch` rechaza una dirección no pública.

#### Significado
La protección evita que una URL alcance servicios internos.

#### Comprobación
Revise host y resolución DNS con su administrador.

#### Solución paso a paso
1. Verifique que no sea una URL errónea o maliciosa. 2. Use una fuente pública. 3. Solo para un servidor local controlado, permita ese host exacto con `--allow-private-host HOST`.

#### Cuándo pedir ayuda
Comparta el host anonimizado y si es un entorno de pruebas.

### 21. `robots.txt` impide la descarga

#### Síntoma
El informe marca `disallowed by robots.txt`.

#### Significado
El sitio pide que esa ruta no sea obtenida automáticamente.

#### Comprobación
Revise el informe de `fetch` y la política del sitio.

#### Solución paso a paso
1. Respete la indicación. 2. Busque una ruta oficial permitida. 3. Solicite una copia o permiso. 4. Importe una copia legal manualmente.

#### Cuándo pedir ayuda
Comparta dominio, alias y motivo; no pida evadir la regla.

### 22. Respuesta HTTP 401

#### Síntoma
`fetch` registra `HTTP 401`.

#### Significado
La ruta exige autenticación.

#### Comprobación
Revise el recurso y `reports/fetch-*.md`.

#### Solución paso a paso
1. No incruste credenciales. 2. Obtenga legalmente la copia con los medios normales. 3. Impórtela con `bibgraph import`.

#### Cuándo pedir ayuda
Comparta estado y dominio, nunca credenciales ni cookies.

### 23. Respuesta HTTP 403

#### Síntoma
`fetch` registra `HTTP 403`.

#### Significado
El servidor prohíbe la solicitud; no es transitorio para bibgraph.

#### Comprobación
Revise URL, derechos e informe.

#### Solución paso a paso
1. No intente eludir el control. 2. Busque una ruta oficial autorizada. 3. Aporte una copia legal si dispone de ella.

#### Cuándo pedir ayuda
Comparta código, dominio y alias.

### 24. Respuesta HTTP 404

#### Síntoma
`fetch` registra `HTTP 404`.

#### Significado
El recurso no existe en esa dirección.

#### Comprobación
Abra la página informativa oficial manualmente, sin automatizar accesos.

#### Solución paso a paso
1. Corrija una errata. 2. Localice una URL oficial vigente. 3. Actualice el catálogo y fecha de observación. 4. Valide y repita.

#### Cuándo pedir ayuda
Comparta URL sin parámetros sensibles y fecha.

### 25. Respuesta HTTP 429

#### Síntoma
El servidor responde `429`.

#### Significado
Se han hecho demasiadas solicitudes.

#### Comprobación
Revise intentos y `Retry-After` en el informe.

#### Solución paso a paso
1. Deje terminar los reintentos limitados. 2. Espere. 3. Configure el correo. 4. Aumente `--delay`. 5. No lance varias descargas simultáneas.

#### Cuándo pedir ayuda
Comparta dominio, hora, demora e intentos.

### 26. Tiempo de espera agotado

#### Síntoma
El informe registra un error de transporte o tiempo agotado.

#### Significado
La respuesta no llegó dentro del límite.

#### Comprobación
Compruebe conexión y disponibilidad del sitio; para PDF revise `--pdf-timeout`.

#### Solución paso a paso
1. Espere y repita una vez. 2. Reduzca el alcance con `--alias`. 3. Para conversión PDF, aumente razonablemente `--pdf-timeout`. 4. Registre el fallo si persiste.

#### Cuándo pedir ayuda
Comparta fase, alias y mensaje; no contenido.

### 27. El archivo supera el límite

#### Síntoma
El informe dice que la respuesta superó 67.108.864 bytes.

#### Significado
El límite fijo de descarga es 64 MiB.

#### Comprobación
Revise tamaño publicado y que la URL sea el documento correcto.

#### Solución paso a paso
1. No fuerce la descarga. 2. Verifique si recibió otro archivo. 3. Obtenga legalmente una copia y considere importarla localmente. 4. Conserve el informe.

#### Cuándo pedir ayuda
Comparta tamaño, tipo y dominio; no el archivo.

### 28. El tipo MIME declarado no coincide

#### Síntoma
`fetch` registra discrepancia entre tipo esperado, declarado y observado.

#### Significado
El servidor entregó otro tipo de contenido o está mal configurado.

#### Comprobación
Revise `expected_media_type`, URL e informe.

#### Solución paso a paso
1. Confirme manualmente la URL. 2. Corrija la URL o su extensión en el catálogo. 3. No renombre contenido incorrecto para engañar la comprobación. 4. Reimporte y valide.

#### Cuándo pedir ayuda
Comparta los tres tipos indicados y el dominio.

### 29. La extensión es PDF, pero el contenido no

#### Síntoma
Se informa que los bytes mágicos no empiezan por `%PDF-`.

#### Significado
El contenido no es un PDF auténtico.

#### Comprobación
Revise si la URL redirige o muestra una página.

#### Solución paso a paso
1. No abra el archivo como confiable. 2. Encuentre la descarga oficial real. 3. Actualice la URL. 4. Repita `fetch`.

#### Cuándo pedir ayuda
Comparta hash, tamaño y mensaje, no el archivo dudoso.

### 30. Se recibe una página de inicio de sesión

#### Síntoma
Se esperaba un PDF y se detecta HTML de acceso, pago o error.

#### Significado
La URL no entrega el documento sin una sesión.

#### Comprobación
Revise la página informativa y derechos.

#### Solución paso a paso
1. No automatice el inicio de sesión. 2. Obtenga la copia mediante acceso autorizado. 3. Guárdela legalmente. 4. Use `bibgraph import`.

#### Cuándo pedir ayuda
Comparta estado, tipo y dominio; nunca sesión, contraseña o documento.

### 31. `fetch` termina con código 2

#### Síntoma
La descarga acaba con estado 2.

#### Significado
Faltó algún recurso requerido o texto completo exigido.

#### Comprobación
Abra el informe `reports/fetch-*.md` más reciente.

#### Solución paso a paso
1. Localice `required_failures` o `works_without_fulltext`. 2. Corrija solo causas autorizadas. 3. Importe copias legales cuando proceda. 4. Repita el alias afectado.

#### Cuándo pedir ayuda
Comparta resumen, alias y motivos, ocultando URL privadas.

### 32. `fetch` termina con código 4

#### Síntoma
La descarga acaba con estado 4.

#### Significado
Algún cuerpo falló integridad, tamaño o tipo; tiene prioridad sobre el estado 2.

#### Comprobación
Revise `integrity_failures` en el informe.

#### Solución paso a paso
1. No use el artefacto rechazado. 2. Revise URL, tipo y tamaño. 3. Corrija el catálogo o aporte copia legal. 4. Repita.

#### Cuándo pedir ayuda
Comparta motivo, hash si existe y alias.

### 33. No hay documento para extraer

#### Síntoma
`extract` no encuentra artefactos adecuados.

#### Significado
La obra no se descargó ni se importó correctamente.

#### Comprobación
Revise informes de `fetch` y `data/state.sqlite3` mediante la salida de la aplicación, sin editar la base.

#### Solución paso a paso
1. Ejecute `fetch --alias ALIAS`. 2. Atienda la cola manual. 3. Importe una copia legal. 4. Repita `extract --alias ALIAS`.

#### Cuándo pedir ayuda
Comparta alias y estados, no la base ni el documento.

### 34. La extracción no encuentra referencias

#### Síntoma
El conteo de referencias es cero o avisa que no pudo segmentarlas.

#### Significado
La obra puede no tener bibliografía, usar un formato no reconocido o haberse extraído mal.

#### Comprobación
Revise el campo `references` en `data/documents/ALIAS.json` y `reports/extract.md`.

#### Solución paso a paso
1. Compruebe visualmente el documento. 2. Distinga `not_present` de `not_applicable`. 3. Registre revisión humana. 4. No invente referencias.

#### Cuándo pedir ayuda
Comparta estado, adaptador y encabezados anonimizados.

### 35. Hay referencias ambiguas o sin resolver

#### Síntoma
`resolve` crea una cola de revisión.

#### Significado
No existe una coincidencia fuerte y única.

#### Comprobación
Revise `reports/resolve.md`.

#### Solución paso a paso
1. Compare autores, título, año y DOI. 2. Consulte fuentes autorizadas. 3. No fusione por intuición. 4. Conserve como ambigua si no hay evidencia.

#### Cuándo pedir ayuda
Comparta cadena bibliográfica y candidatos, sin notas privadas.

### 36. `resolve` pide ejecutar `extract`

#### Síntoma
Ve una advertencia de que no hay documentos extraídos.

#### Significado
`data/documents/` está vacío; no hay referencias que resolver.

#### Comprobación
```bash
find data/documents -maxdepth 1 -name '*.json' -print
```

#### Solución paso a paso
1. Adquiera o importe documentos. 2. Ejecute `extract`. 3. Revise su informe. 4. Ejecute `resolve`.

#### Cuándo pedir ayuda
Comparta conteos de adquisición y extracción.

### 37. `analyze` no encuentra `data/references.jsonl`

#### Síntoma
`analyze` termina con código 2 y pide `resolve`.

#### Significado
Todavía no existe la exportación de referencias.

#### Comprobación
```bash
test -f data/references.jsonl && echo encontrado
```

#### Solución paso a paso
1. Ejecute `extract`. 2. Ejecute `resolve`. 3. Atienda errores. 4. Repita `analyze`.

#### Cuándo pedir ayuda
Comparta salidas resumidas de esos comandos.

### 38. `build-site` se niega por datos incompletos

#### Síntoma
El comando termina con 2 y enumera motivos de incompletitud.

#### Significado
Falta el catálogo fuente o no hay relaciones de dependencia.

#### Comprobación
Revise `config/corpus.json`, `config/dependencies.json` y `validate`.

#### Solución paso a paso
1. Importe datos reales. 2. Revise dependencias. 3. Valide. 4. Solo para inspección, use `--allow-incomplete` y lea sus avisos.

#### Cuándo pedir ayuda
Comparta los motivos exactos, no datos privados.

### 39. El sitio se genera sin estilos

#### Síntoma
El HTML parece texto sin diseño o falta `site.css`.

#### Significado
Los recursos de `site-src/` no se copiaron o el sitio se movió parcialmente. La implementación actual debe fallar si no encuentra CSS/JS.

#### Comprobación
```bash
test -f build/site/site.css && echo encontrado
```

#### Solución paso a paso
1. No copie solo HTML. 2. Restaure `site-src/site.css` y `site.js`. 3. Reconstruya. 4. Ejecute `check-site`.

#### Cuándo pedir ayuda
Comparta errores de construcción y listado de nombres, no contenidos.

### 40. `check-site` encuentra enlaces rotos

#### Síntoma
El informe contiene `broken-link` o `broken-anchor`.

#### Significado
Una página apunta a un archivo o sección inexistente.

#### Comprobación
Abra `reports/check-site.md`.

#### Solución paso a paso
1. Identifique página y destino. 2. Reconstruya el sitio completo. 3. No mueva archivos sueltos. 4. Compruebe de nuevo.

#### Cuándo pedir ayuda
Comparta código, ubicación y destino, sin rutas personales.

### 41. La comprobación pública encuentra una ruta privada

#### Síntoma
`check-site --public` informa `private-path` o `absolute-local-path`.

#### Significado
La salida revela una carpeta privada o una ruta del equipo.

#### Comprobación
Revise el archivo indicado en `reports/check-site.md`.

#### Solución paso a paso
1. No publique. 2. Elimine la salida `publish/` solo después de respaldar lo necesario. 3. Reconstruya con `build-site --public`, no copiando el sitio local. 4. Compruebe de nuevo.

#### Cuándo pedir ayuda
Comparta el código y una ruta redactada.

### 42. La publicación requiere evidencia de licencia

#### Síntoma
Validación o informe retiene resumen/texto por falta de evidencia.

#### Significado
Una marca de publicación no basta sin `license_evidence_url`.

#### Comprobación
Revise derechos en `config/corpus.json` y `reports/publication.md`.

#### Solución paso a paso
1. Localice evidencia oficial. 2. Registre licencia y URL. 3. Si no existe, mantenga los pasajes privados. 4. Valide y reconstruya.

#### Cuándo pedir ayuda
Comparta licencia y enlace público, no el texto retenido.

### 43. El puerto 8000 está ocupado

#### Síntoma
El servidor informa que la dirección ya está en uso.

#### Significado
Otro programa usa ese puerto.

#### Comprobación
Pruebe `http://127.0.0.1:8000/` por si ya es su servidor.

#### Solución paso a paso
1. Detenga el servidor anterior con `Ctrl+C` si lo controla. 2. Si no, use 8080. 3. Abra la URL con el nuevo puerto.

#### Cuándo pedir ayuda
Comparta el mensaje y puerto, no información de red privada.

### 44. El navegador no abre el sitio local

#### Síntoma
`127.0.0.1:8000` no responde.

#### Significado
El servidor no está activo, usa otro puerto o se ejecuta en otro entorno.

#### Comprobación
Mire la terminal del servidor y confirme la URL exacta con `http://`.

#### Solución paso a paso
1. Mantenga el comando en ejecución. 2. Confirme puerto. 3. En WSL pruebe desde el navegador del mismo equipo. 4. Reinicie el servidor.

#### Cuándo pedir ayuda
Comparta mensaje del servidor, sistema y URL sin datos externos.

### 45. La terminal parece bloqueada tras iniciar el servidor

#### Síntoma
No vuelve el indicador para escribir.

#### Significado
Es normal: el servidor ocupa esa terminal.

#### Comprobación
Abra el sitio en el navegador.

#### Solución paso a paso
1. Deje esa terminal abierta. 2. Abra otra para otros comandos. 3. Pulse `Ctrl+C` cuando termine.

#### Cuándo pedir ayuda
Pida ayuda solo si no responde a `Ctrl+C`; indique el sistema.

### 46. Al cerrar la terminal, el sitio deja de responder

#### Síntoma
La página funcionaba y deja de hacerlo al cerrar la ventana.

#### Significado
El servidor era un proceso temporal ligado a esa terminal.

#### Comprobación
Abra la URL y observe el error de conexión.

#### Solución paso a paso
1. Abra otra terminal. 2. Entre en el proyecto. 3. Inicie de nuevo el servidor. 4. Mantenga la terminal abierta.

#### Cuándo pedir ayuda
Indique el comando usado y puerto.

### 47. Se modificó accidentalmente `config/corpus.json`

#### Síntoma
Faltan datos o `validate` falla tras una edición/importación.

#### Significado
El archivo fuente de verdad cambió.

#### Comprobación
```bash
git diff -- config/corpus.json
```

#### Solución paso a paso
1. No siga ejecutando la canalización. 2. Compare `config/corpus.json.backup`. 3. Restaure con `cp config/corpus.json.backup config/corpus.json` si es la copia correcta. 4. Valide.

#### Cuándo pedir ayuda
Comparta el diff sin URL, licencias privadas ni notas sensibles.

### 48. `make` no está instalado

#### Síntoma
Ve `make: command not found`.

#### Significado
Los atajos opcionales no están disponibles.

#### Comprobación
```bash
command -v make
```

#### Solución paso a paso
1. Use directamente `./bin/bibgraph ...`. 2. Para servir, use `python3 -m http.server ...`. 3. Instale Make solo si lo desea.

#### Cuándo pedir ayuda
Indique el atajo deseado para recibir su equivalente.

### 49. Una forma de iniciar funciona y la otra no

#### Síntoma
Funciona `PYTHONPATH=src python3 -m bibgraph` pero no el lanzador, o al revés.

#### Significado
Hay una diferencia de shell, permiso o intérprete.

#### Comprobación
Revise `head -1 bin/bibgraph`, `command -v bash` y `command -v python3`.

#### Solución paso a paso
1. Entre en la raíz. 2. En Windows use WSL/Git Bash. 3. Corrija permiso de ejecución. 4. Use temporalmente la forma que funciona.

#### Cuándo pedir ayuda
Comparta comandos, shell y errores exactos.

### 50. El comando se ejecutó desde otra carpeta

#### Síntoma
Faltan `config/`, `site-src/` o el lanzador.

#### Significado
El punto (`.`) se resolvió como una carpeta equivocada.

#### Comprobación
```bash
pwd
```

#### Solución paso a paso
1. Use `cd RUTA/AL/PROYECTO`. 2. Compruebe `bin/bibgraph`. 3. O coloque `--root RUTA/AL/PROYECTO` antes del subcomando.

#### Cuándo pedir ayuda
Comparta `pwd` redactado y nombres de archivos del nivel superior.

### 51. Un JSON tiene puntuación incorrecta

#### Síntoma
Se menciona `JSONDecodeError`, una coma, llave o comilla.

#### Significado
El archivo no cumple la sintaxis JSON.

#### Comprobación
```bash
python3 -m json.tool RUTA/AL/ARCHIVO.json
```

#### Solución paso a paso
1. Trabaje sobre una copia. 2. Use comillas dobles. 3. Quite comas finales. 4. Empareje llaves/corchetes. 5. Valide de nuevo.

#### Cuándo pedir ayuda
Comparta línea, columna y fragmento anonimizado.

### 52. El sitio local contiene información no publicable

#### Síntoma
Ve textos, rutas o anotaciones privadas en `build/site/`.

#### Significado
Es el comportamiento esperado de la construcción local.

#### Comprobación
Confirme que la ruta es `build/site/`, no `publish/`.

#### Solución paso a paso
1. No publique `build/site/`. 2. Revise derechos. 3. Ejecute `build-site --public`. 4. Revise `publication.md`. 5. Ejecute la comprobación pública.

#### Cuándo pedir ayuda
Comparta solo el tipo de fuga, nunca el contenido.

### 53. Una anotación tiene `pass_status` no permitido

#### Síntoma
`annotate` rechaza el estado.

#### Significado
Solo admite `unread`, `pass_1`, `pass_2` o `pass_3`.

#### Comprobación
```bash
python3 -m json.tool ARCHIVO.json
```

#### Solución paso a paso
1. Abra el JSON. 2. Sustituya el valor por uno exacto y en minúsculas. 3. Valide la sintaxis. 4. Repita `annotate`.

#### Cuándo pedir ayuda
Comparta solo `pass_status` y el error, no sus notas.

## 28. Recuperación y copias de seguridad

Antes de editar, haga copias con fecha o etiqueta:

```bash
cp config/corpus.json config/corpus.json.backup
```

```bash
cp config/dependencies.json config/dependencies.json.backup
```

```bash
cp config/reading-profile.json config/reading-profile.json.backup
```

```bash
cp -a annotations annotations.backup
```

`config/` y `annotations/` contienen decisiones y trabajo humano: respáldelos. `private/` contiene material posiblemente privado; protéjalo y no lo publique. `data/state.sqlite3` conserva estado local y no debe borrarse como arreglo genérico. `data/documents/`, JSONL derivados, `reports/`, `build/` y `publish/` pueden regenerarse en distinto grado, pero los informes pueden ser valiosos para auditoría.

**Advertencia:**

```bash
make clean
```

elimina recursivamente **solo** `build/`, `publish/` y cada directorio llamado `__pycache__` bajo el proyecto. No elimina `private/`, `data/state.sqlite3` ni `annotations/`. Aun así, confirme que está en el proyecto correcto antes de usarlo.

## 29. Privacidad y publicación segura

Antes de publicar:

- [ ] Se usó `./bin/bibgraph build-site --public`.
- [ ] Se ejecutó `./bin/bibgraph check-site publish --public` sin errores.
- [ ] Se revisó `reports/publication.md`.
- [ ] Cada pasaje copiado tiene licencia y evidencia de licencia.
- [ ] Las anotaciones publicables tienen `"publish": true` de forma intencional.
- [ ] No quedan rutas locales absolutas ni valores con apariencia de secretos.
- [ ] No hay PDF, base de datos, caché ni material de `private/`.
- [ ] No se va a publicar `build/site/`.
- [ ] Se publicará únicamente el contenido de `publish/`.

## 30. Glosario

| Término | Definición |
| --- | --- |
| API | Servicio que permite consultas entre programas; Crossref ofrece una. |
| Biblioteca estándar | Herramientas incluidas con Python, sin instalar paquetes de terceros. |
| CAPTCHA | Prueba destinada a distinguir personas de programas; bibgraph no la elude. |
| CSS | Archivo que da presentación visual al HTML. |
| Crossref | Servicio externo de metadatos bibliográficos usado solo con `--online`. |
| DAG | Grafo dirigido sin ciclos; modela un orden posible de lectura. |
| DOI | Identificador persistente de una publicación. |
| Hash SHA-256 | Huella calculada para identificar bytes y detectar cambios. |
| HTML | Formato de páginas web; bibgraph puede extraerlo y generarlo. |
| HTTP/HTTPS | Formas de transferir contenido web; HTTPS cifra la conexión. |
| JSON | Texto estructurado con objetos, listas, comillas y comas. |
| JSONL | Un objeto JSON por línea, usado para registros reproducibles. |
| Licencia | Permiso legal que define usos y redistribución. |
| Markdown | Texto con marcas sencillas, como tablas con `|`. |
| MIME o tipo de contenido | Etiqueta del formato, como `application/pdf`. |
| Poppler | Conjunto de herramientas PDF que incluye `pdftotext`. |
| Procedencia | Registro de dónde se obtuvo un dato o archivo. |
| Python | Lenguaje con el que está implementada la aplicación. |
| Ranking | Orden calculado a partir de criterios publicados. |
| `robots.txt` | Archivo con orientación de rastreo de un sitio web. |
| SQLite | Base de datos local incluida normalmente con Python. |
| SSL/TLS | Protección criptográfica usada por HTTPS. |
| URL | Dirección de un recurso en la Web. |
| WSL | Entorno Linux dentro de Windows. |

Los conceptos terminal, comando, carpeta, catálogo, alias, recurso, manifiesto, metadatos, grafo, dependencia, sitio estático, construcción y código de salida se definen en la sección 3.

## 31. Lista final de comprobación

- [ ] El entorno fue comprobado.
- [ ] El catálogo fue importado.
- [ ] Las dependencias fueron revisadas.
- [ ] La configuración pasa la validación.
- [ ] Las descargas autorizadas terminaron o sus fallos están registrados.
- [ ] Las copias manuales fueron importadas.
- [ ] La extracción fue revisada.
- [ ] Las referencias ambiguas fueron identificadas.
- [ ] El análisis fue generado.
- [ ] El sitio local fue comprobado.
- [ ] La versión pública pasó su comprobación.
- [ ] Las licencias fueron revisadas.

## Parte II. Hoja rápida de una página

1. Entre en el proyecto: `cd RUTA/AL/PROYECTO`.
2. Compruebe: `./bin/bibgraph doctor`.
3. Prepare la tabla descrita en la sección 7.
4. Pruebe: `./bin/bibgraph import-catalogue phase-1-access-verification.md --observed-on AAAA-MM-DD --dry-run`.
5. Respalde `config/corpus.json` e importe sin `--dry-run`.
6. Revise a mano `config/dependencies.json` y `config/reading-profile.json`.
7. Valide: `./bin/bibgraph validate --strict`.
8. Configure `BIBGRAPH_CONTACT_EMAIL` y ejecute `./bin/bibgraph fetch --keep-going`.
9. Para copias legales faltantes: `./bin/bibgraph import ALIAS ARCHIVO`.
10. Ejecute, por separado: `extract`, `resolve`, `analyze`.
11. Cree el sitio: `./bin/bibgraph build-site --local`.
12. Compruébelo: `./bin/bibgraph check-site build/site`.
13. Sírvalo en local: `python3 -m http.server --bind 127.0.0.1 --directory build/site 8000`.
14. Abra `http://127.0.0.1:8000/`; detenga con `Ctrl+C`.
15. Para publicar, use exclusivamente `build-site --public`, revise `reports/publication.md`, compruebe `publish --public` y suba solo `publish/`.

## Parte III. Tabla resumen de todos los comandos

| Subcomando real | Opciones/argumentos principales | Uso habitual o avanzado |
| --- | --- | --- |
| `doctor` | Sin opciones propias. | Habitual. |
| `validate` | `--strict`. | Habitual; estricto recomendado antes del flujo. |
| `import-catalogue` | `path`, `--observed-on`, `--output`, `--dry-run`. | Habitual al preparar el corpus. |
| `fetch` | `--strict`, `--keep-going`, `--alias` repetible, `--require-fulltext-all`, `--delay`. | Habitual. |
| `fetch` | `--allow-http`, `--allow-private-host` repetible, `--no-robots`. | Avanzado y de seguridad reducida. |
| `import` | `alias`, `file`, `--role`. | Habitual cuando hay copias legales. |
| `extract` | `--strict`, `--alias` repetible, `--pdf-timeout`. | Habitual. |
| `resolve` | `--strict`, `--online`, `--no-discovery`. | Habitual; red y control de descubrimiento son opcionales. |
| `analyze` | Sin opciones propias. | Habitual. |
| `promote` | `--max-new`, `--min-citations`, `--year-from`, `--year-to`. | Avanzado; propuesta humana. |
| `annotate` | `alias`, `file`. | Habitual en revisión humana. |
| `build-site` | `--local` o `--public`, `--output`, `--allow-incomplete`. | Local habitual; público delicado. |
| `check-site` | `path`, `--public`. | Obligatorio antes de usar/publicar. |

Opciones globales, siempre antes del subcomando: `--root RUTA` y `--json`.

## Parte IV. Árbol de decisión de solución de problemas

```text
¿El comando llega a iniciarse?
├─ No → ¿"python3" falta? → Instalar Python 3.10+.
│       ├─ ¿"Permission denied"? → Dar ejecución al lanzador o usar PYTHONPATH.
│       └─ ¿Faltan archivos? → Entrar en la raíz o usar --root antes del comando.
└─ Sí → ¿Código 3?
        ├─ Sí → Validar JSON y ejecutar validate; corregir manifiestos.
        └─ No → ¿Código 4?
                ├─ Sí → No usar el archivo; revisar tamaño, MIME, firma y URL.
                └─ No → ¿Código 2?
                        ├─ fetch → Revisar recursos requeridos y copias legales.
                        ├─ extract → Revisar pdftotext y cola manual.
                        ├─ resolve/analyze → Ejecutar primero la fase anterior.
                        └─ build/check → Completar datos o corregir enlaces/fugas.

¿El problema es al ver el sitio?
├─ Sin estilos → Reconstruir y comprobar site.css.
├─ No conecta → Mantener servidor abierto y confirmar puerto.
└─ Contiene datos privados → Es local; crear publish/ con la lista permitida.
```

## Parte V. Lista de comprobación antes de publicar

- [ ] La fuente bibliográfica real fue suministrada y no quedan datos provisionales engañosos.
- [ ] Las dependencias y elecciones fueron revisadas por una persona.
- [ ] `validate --strict` no informa problemas pendientes.
- [ ] Las licencias y sus URL de evidencia se comprobaron en fuentes autorizadas.
- [ ] Cada anotación con `"publish": true` fue revisada expresamente.
- [ ] Se ejecutó `./bin/bibgraph build-site --public`.
- [ ] Se leyó `reports/publication.md` completo.
- [ ] Se ejecutó `./bin/bibgraph check-site publish --public` y devolvió 0.
- [ ] No hay documentos, bases, caché, rutas locales, secretos ni notas privadas.
- [ ] No se copiará `build/site/`.
- [ ] Solo se publicará el contenido de `publish/`.

## Parte VI. Aspectos que no pudieron verificarse

- El catálogo real `phase-1-access-verification.md` no está incluido. No se pudieron verificar títulos, autores, URL, accesos ni licencias reales.
- El diagrama original de relaciones no está incluido. Las dependencias reales y las dos elecciones no pudieron resolverse; el archivo actual tiene nodos pero cero relaciones.
- La precisión sobre documentos académicos reales no está validada externamente. Las pruebas cuantitativas usan casos creados dentro del propio repositorio y detectan regresiones, no demuestran precisión general.
- La compatibilidad nativa con Símbolo del sistema o PowerShell no existe en el lanzador Bash. WSL y Git Bash son alternativas del entorno, pero no se declara una matriz formal de plataformas.
- Los permisos legales de cada futura copia aportada por el usuario no pueden comprobarse automáticamente; corresponden al usuario y a la evidencia registrada.
- No existe un esquema JSON formal completo para anotaciones. Solo pudieron documentarse las validaciones implementadas: objeto raíz y los cuatro valores de `pass_status`.
- No se ejecutaron descargas ni operaciones de la canalización durante la investigación documental. Las descripciones proceden de inspección estática del código, configuración, pruebas y documentación del repositorio.
