// Starts the page: one object of each class, then the first route. Loads last
// (see index.html), so every class is defined by now. The objects are globals the
// classes use by name, each created before anything can call it.

FolderPicker.guardWindow();
ChartDownloads.wire();

const workspaces = new Workspaces();      // the analysis's and the live run's session and results
const router = new Router();
const player = new ClipPlayer();
const recordings = new RecordingsList();

const sessionLabels = new SessionLabels();
const labelReader = new LabelReader();
const labelPage = new LabelPage();
const analysis = new AnalysisMode();
const resultsView = new ResultsView();

const livePanel = new LivePanel();
const liveSetup = new LiveSetupPage();
const live = new LiveRun();

const groundTruth = new GroundTruth();
const cal = new Calibration();
const datasetLibrary = new DatasetLibrary();
const truthPage = new TruthPage();
const reportPage = new ReportPage();

new ServerHeartbeat().start();
router.route();
