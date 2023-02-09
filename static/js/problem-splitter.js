$(document).ready(function() {

  x = new SelectionMenu({
    container: document.querySelector('#problem'),
    content: document.querySelector('#splitter-menu'),
    minlength: 2,
    handler: function (event) {
      var target = event.target,
        id = target.id || target.parentNode.id  // for the <strong> in the #create-new-recall
      ;
//      console.log('Handling click on', id, 'with text "' + this.selectedText + '"');
      this.hide(true);  // hide the selection after hiding the menu; useful if opening a link in a new tab
    },
    onselect: function (e) {
//      console.log(this.selectedText);
      $("#split_feedback").attr('href', $('#split_feedback').attr('href').replace(/(&problem=)[^]*/, "&problem=" + encodeURIComponent(this.selectedText)));
    },
    debug: false
  });
})
