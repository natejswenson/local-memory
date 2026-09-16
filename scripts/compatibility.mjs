#!/usr/bin/env node
import {DatabaseSync, backup} from 'node:sqlite';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
process.umask(0o077);
const root=fs.mkdtempSync(path.join(os.tmpdir(),'memory-spike-'));
try {
 const file=path.join(root,'probe.sqlite3');
 const db=new DatabaseSync(file);
 const sqlite=db.prepare('select sqlite_version() as v').get().v;
 assert.ok(sqlite.split('.').map(Number).reduce((n,x)=>n*1000+x,0)>=3051003,'Linked SQLite must include WAL-reset fix (>=3.51.3)');
 assert.equal(db.prepare('PRAGMA journal_mode=WAL').get().journal_mode,'wal');
 db.exec('PRAGMA synchronous=FULL; CREATE TABLE probe (id INTEGER PRIMARY KEY, value TEXT); BEGIN IMMEDIATE; INSERT INTO probe VALUES (1,\'synthetic\'); COMMIT;');
 let fts5=true;
 try {db.exec('CREATE VIRTUAL TABLE probe_fts USING fts5(value, tokenize="unicode61"); INSERT INTO probe_fts VALUES (\'synthetic hashtags\')'); assert.equal(db.prepare('SELECT count(*) AS n FROM probe_fts WHERE probe_fts MATCH ?').get('"hashtags"').n,1);} catch {fts5=false;}
 assert.equal('synthetic hashtags'.normalize('NFC').toLowerCase().match(/[\p{L}\p{N}]+/gu).includes('hashtags'),true);
 const snap=path.join(root,'snapshot.sqlite3');
 await backup(db,snap);
 const copy=new DatabaseSync(snap); assert.equal(copy.prepare('PRAGMA integrity_check').get().integrity_check,'ok'); assert.equal(copy.prepare('SELECT value FROM probe').get().value,'synthetic'); copy.close(); db.close();
 const child=spawnSync(process.execPath,['--input-type=module','-e','import {DatabaseSync} from "node:sqlite"; const d=new DatabaseSync(process.argv[1]); console.log(d.prepare("SELECT value FROM probe").get().value); d.close();',file],{encoding:'utf8'});
 assert.equal(child.status,0); assert.equal(child.stdout.trim(),'synthetic');
 assert.equal(fs.statSync(root).mode&0o777,0o700); assert.equal(fs.statSync(file).mode&0o777,0o600);
 console.log(JSON.stringify({node:process.version,executable:process.execPath,platform:process.platform,arch:process.arch,build_sqlite:process.versions.sqlite,linked_sqlite:sqlite,wal:true,full_sync:true,transaction:true,online_backup:true,integrity:true,fts5,scan:true,restart:true,permissions:'0700/0600'},null,2));
} finally {fs.rmSync(root,{recursive:true,force:true});}
