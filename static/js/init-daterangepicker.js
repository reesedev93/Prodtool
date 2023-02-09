// Callback method that sets visible and hidden date fields when date is selected.
function setDate(start, end) {
  // Set visible input fields to selected time
  $(element).val(start.format('MMM D YYYY') + ' - ' + end.format('MMM D YYYY'));
  
  // Set hidden fields to values that ORM will accept without hassle so we can filter feedback.
  // We covert to UTC to query because feedback is stored in db in UTC
  $("#id_start_date").val(start.utc().format("YYYY-MM-DD"));
  $("#id_end_date").val(end.utc().format("YYYY-MM-DD"));
}

function initDateRangePicker(element, obj) {
  // Init date range picker
  $(element).daterangepicker({
    autoUpdateInput: false,
    alwaysShowCalendars: true,
    opens: "left",
    drops: "up",
    locale: { 
      "cancelLabel": 'Clear',
      "format": "MMM D YYYY",
      "separator": " - ",
    },  
    ranges: {
       'Today': [moment(), moment()],
       'Last 7 Days': [moment().subtract(6, 'days'), moment()],
       'Last 30 Days': [moment().subtract(29, 'days'), moment()],
       'This Month': [moment().startOf('month'), moment().endOf('month')],
       'Last Month': [moment().subtract(1, 'month').startOf('month'), moment().subtract(1, 'month').endOf('month')],
       'Year to date': [moment().startOf('year'), moment()]
    }
  }, function(start, end) {
      $(element).val(start.format('MMM D YYYY') + ' - ' + end.format('MMM D YYYY'));
      
      start_date_field = "#id_" + obj + "_start_date"
      end_date_field = "#id_" + obj + "_end_date"

      // Set hidden fields to values that ORM will accept without hassle so we can filter feedback.
      // We covert to UTC to query because feedback is stored in db in UTC
      $(start_date_field).val(start.utc().format("YYYY-MM-DD"));
      $(end_date_field).val(end.utc().format("YYYY-MM-DD"));

  }).on('cancel.daterangepicker', function(ev, picker) {
      // Clear date range when Clear button clicked
      start_date_field = "#id_" + obj + "_start_date"
      end_date_field = "#id_" + obj + "_end_date"

      $(element).val('');
      $(start_date_field).val('');
      $(end_date_field).val('');
  });
}
