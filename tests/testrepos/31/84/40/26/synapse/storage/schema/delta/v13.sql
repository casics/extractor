/* Copyright 2015 OpenMarket Ltd
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

CREATE TABLE IF NOT EXISTS application_services(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT,
    token TEXT,
    hs_token TEXT,
    sender TEXT,
    UNIQUE(token) ON CONFLICT ROLLBACK
);

CREATE TABLE IF NOT EXISTS application_services_regex(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    as_id INTEGER NOT NULL,
    namespace INTEGER,  /* enum[room_id|room_alias|user_id] */
    regex TEXT,
    FOREIGN KEY(as_id) REFERENCES application_services(id)
);



