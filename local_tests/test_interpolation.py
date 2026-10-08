import unittest
from unittest.mock import MagicMock,patch
import numpy as np
from src.tools.interpolation import validate_points,interp

class InterpolationTests(unittest.TestCase):
    def test_points_have_finite_rectangular_shape(self):
        self.assertEqual(validate_points([[1,2,3]],3).shape,(1,3))
        for points in [[],[[1,2]],[[1,2,float('nan')]],[[1,2,float('inf')]]]:
            with self.assertRaises(ValueError):validate_points(points,3)

    @patch('src.tools.interpolation.cast',side_effect=lambda x:x)
    def test_failed_evaluation_removes_temporary_node(self,_cast):
        model=MagicMock();result=model.java.result.return_value
        result.dataset.return_value.tags.return_value=['dset1']
        collection=result.numerical.return_value;node=MagicMock()
        def create(tag,kind):
            collection.tags.return_value=[tag]
            return node
        collection.create.side_effect=create;node.getData.side_effect=RuntimeError('bad expression')
        with self.assertRaisesRegex(RuntimeError,'bad expression'):
            interp(model,'dset1',['missing'],[1],1,np.array([[1.,2.,3.]]))
        collection.remove.assert_called_once_with(collection.create.call_args.args[0])

    def test_invalid_indices_do_not_create_evaluation(self):
        model=MagicMock()
        for inner in [[],[0],[1,1]]:
            with self.assertRaises(ValueError):interp(model,'dset1',['x'],inner,1)
        model.java.result.assert_not_called()

if __name__=='__main__':unittest.main()
