import { google } from 'googleapis';

try {
  const siteUrl = 'https://camp-gear-lab.com/';
  const inspectionUrl = process.argv[2];
  if (!/^https:\/\/camp-gear-lab\.com\/articles\/[a-z0-9-]+$/.test(inspectionUrl)) {
    throw new Error('invalid_url');
  }
  const auth = new google.auth.GoogleAuth({
    credentials: JSON.parse(process.env.INDEXING_CREDENTIALS),
    scopes: ['https://www.googleapis.com/auth/webmasters.readonly'],
  });
  const client = google.searchconsole({version: 'v1', auth});
  const {data} = await client.urlInspection.index.inspect({
    requestBody: {siteUrl, inspectionUrl, languageCode: 'en-US'},
  }, {timeout: 10000});
  const result = data.inspectionResult?.indexStatusResult;
  if (!result?.verdict) throw new Error('missing_result');
  const {verdict, coverageState, googleCanonical, lastCrawlTime} = result;
  console.log(JSON.stringify({verdict, coverageState, googleCanonical, lastCrawlTime}));
} catch (error) {
  const http = error.response?.status;
  console.log(JSON.stringify({error: [401, 403].includes(http) ? 'access_denied' : 'inspection_unavailable'}));
}
