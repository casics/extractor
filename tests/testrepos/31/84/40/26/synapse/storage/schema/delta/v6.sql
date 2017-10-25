/* Copyright 2014, 2015 OpenMarket Ltd
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *    http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
CREATE TABLE IF NOT EXISTS server_tls_certificates(
  server_name TEXT, -- Server name.
  fingerprint TEXT, -- Certificate fingerprint.
  from_server TEXT, -- Which key server the certificate was fetched from.
  ts_added_ms INTEGER, -- When the certifcate was added.
  tls_certificate BLOB, -- DER encoded x509 certificate.
  CONSTRAINT uniqueness UNIQUE (server_name, fingerprint)
);

CREATE TABLE IF NOT EXISTS server_signature_keys(
  server_name TEXT, -- Server name.
  key_id TEXT, -- Key version.
  from_server TEXT, -- Which key server the key was fetched form.
  ts_added_ms INTEGER, -- When the key was added.
  verify_key BLOB, -- NACL verification key.
  CONSTRAINT uniqueness UNIQUE (server_name, key_id)
);
