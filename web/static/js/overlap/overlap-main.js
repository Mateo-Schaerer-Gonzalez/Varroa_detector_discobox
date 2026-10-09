// TEMPORARY, with overlap.html. Starts the page: one object of each class, as
// main.js does for the app. Loads last, so every class is defined by now.

const player = new ClipPlayer();
const check = new OverlapCheck();
const overlapPage = new OverlapPage();

new ServerHeartbeat().start();
overlapPage.reload();
