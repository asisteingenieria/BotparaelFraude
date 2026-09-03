-- Esquema de la base de datos del microservicio (módulo de auditoría).
-- Base propia `bot_firmas`, separada por completo de la BD de FirmaCloud
-- (ver README.md). No hay migraciones versionadas en este proyecto: las
-- tablas se crearon a mano por mysql CLI; este archivo es esa foto exacta
-- (sacada en vivo con SHOW CREATE TABLE) para poder reconstruirla en una
-- instalación nueva.
--
-- Uso:
--   mysql -u root -p < sql/schema.sql
--   -- reemplazar CAMBIAR_PASSWORD por una contraseña real y volcarla en
--   -- .env como BOT_DB_PASSWORD (ver .env.example)

CREATE DATABASE IF NOT EXISTS bot_firmas
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE USER IF NOT EXISTS 'botcartas'@'localhost' IDENTIFIED BY 'CAMBIAR_PASSWORD';
GRANT ALL PRIVILEGES ON bot_firmas.* TO 'botcartas'@'localhost';
FLUSH PRIVILEGES;

USE bot_firmas;

CREATE TABLE IF NOT EXISTS cargas (
  id             CHAR(36)     NOT NULL,
  archivo        VARCHAR(255) NOT NULL,
  modulo         ENUM('original','otro','imagen') NOT NULL DEFAULT 'original',
  total_filas    INT          NOT NULL DEFAULT 0,
  filas_ok       INT          NOT NULL DEFAULT 0,
  filas_error    INT          NOT NULL DEFAULT 0,
  estado         ENUM('procesando','completada','fallida') NOT NULL DEFAULT 'procesando',
  error          TEXT,
  creada_en      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  finalizada_en  DATETIME     DEFAULT NULL,
  PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS cartas (
  id                CHAR(36)     NOT NULL,       -- firma_id (UUID v4)
  carga_id          CHAR(36)     DEFAULT NULL,
  fila_excel        INT          DEFAULT NULL,
  nombre_completo   VARCHAR(200) NOT NULL,
  email             VARCHAR(200) NOT NULL DEFAULT '',
  firma_estilo_id   VARCHAR(50)  NOT NULL,
  firma_fecha_hora  VARCHAR(30)  NOT NULL,
  pdf_path          VARCHAR(500) NOT NULL,
  pdf_bytes         BIGINT       NOT NULL,
  pdf_sha256        CHAR(64)     NOT NULL,
  summary_pdf_path  VARCHAR(500) DEFAULT NULL,
  origen            ENUM('excel','api') NOT NULL DEFAULT 'excel',
  modulo            ENUM('original','otro','imagen') NOT NULL DEFAULT 'original',
  fecha_pixelada    TINYINT(1)   NOT NULL DEFAULT 0,
  creada_en         DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_cartas_nombre (nombre_completo),
  KEY idx_cartas_carga (carga_id),
  CONSTRAINT fk_cartas_carga FOREIGN KEY (carga_id) REFERENCES cargas (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
