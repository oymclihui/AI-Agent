const fs = require('fs-extra');
const path = require('path');

const src = path.join(__dirname, '..', 'build');
const dest = path.join(__dirname, '..', '..', 'public', 'lowcode', 'designer');

async function main() {
  if (!(await fs.pathExists(src))) {
    console.error('Build output not found:', src);
    process.exit(1);
  }
  await fs.emptyDir(dest);
  await fs.copy(src, dest);
  console.log('Copied lowcode designer to', dest);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
