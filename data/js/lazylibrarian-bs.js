function restartQA(e, message, title) {
	var self = this;
	
	bootbox.confirm((window.llTexts && llTexts.restartConfirm) || "Are you sure you want to restart LazyLibrarian?", function(result) {
		if (result) {
			self.restart(message, title);
		}
	});

}

function restart(message, title) {
    window.location.href = "restart";
}

function shutdownQA(e) {
    var self = this;

	bootbox.confirm((window.llTexts && llTexts.shutdownConfirm) || "Are you sure you want to shutdown LazyLibrarian?", function(result) {
		if (result) {
			self.shutdown();
		}
	});
}

function shutdown() {
    window.location.href= "shutdown";
}