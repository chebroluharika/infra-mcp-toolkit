/**
 * WeeklyStatusSection - Embeds the Weekly Status Google Sheet
 * 
 * Simplified component using reusable GoogleSheetsEmbed.
 */
import GoogleSheetsEmbed from '../common/GoogleSheetsEmbed';

const WeeklyStatusSection = ({ selectedRelease }) => {
  return (
    <GoogleSheetsEmbed
      spreadsheetId="1dQAG-RZceHIZJq73mVT8w_R6mTJ2muV9zurUMNr4qrY"
      sheetGid="1674899298"
      title="Weekly Status Report"
      description={`Weekly QE status for ${selectedRelease || 'current release'}`}
      hideExportButtons={true}
    />
  );
};

export default WeeklyStatusSection;
